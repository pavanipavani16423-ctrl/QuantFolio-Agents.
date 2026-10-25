"""LangGraph nodes: one per agent step. Each node is a thin wrapper that

* looks up the run's dependencies (`RunContext`),
* opens its numbered step (Langfuse section + UI event),
* calls the agent / A2A service / MCP tools, and returns only the state keys it owns.
"""

import asyncio
from typing import Any

from langgraph.types import interrupt

from app.a2a import registry
from app.agents import supervisor
from app.agents.intake import research_focus, run_intake
from app.agents.optimizer import build_problem, run_optimizer
from app.agents.preferences import effective_rules, feedback_to_preferences
from app.agents.report import changes, run_report
from app.agents.research import run_research
from app.data import store
from app.data.universe import MARKETS, tickers
from app.evaluation.online import deterministic_scores, llm_scores
from app.graph.context import get_context
from app.schemas import IntakeResult, MandateRules


async def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    nodes, reason = supervisor.decide(state)
    await ctx.emit("decision", {"next": nodes, "reason": reason})
    return {"route": nodes, "decisions": [{"next": nodes, "reason": reason}]}


def route(state: dict[str, Any]) -> list[str] | str:
    return state["route"] or "__end__"


async def intake_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    async with ctx.step("intake", input={"request": state["request"],
                                         "client_id": state["client_id"]}) as step:
        intake, method = await run_intake(ctx, state["request"], state["client_id"])
        preferences = await ctx.load_preferences(state["client_id"]) if ctx.load_preferences else []
        learned = f" Remembered {len(preferences)} preference(s) from past reviews." if preferences else ""
        step.done(f"Question: {intake.research_question}.{learned}", output=intake.model_dump(),
                  method=method, preferences=preferences)
    ctx.tracer.score(trace_id=ctx.trace_id, name="learned_preferences_applied",
                     value=float(len([p for p in preferences if p["kind"] != "note"])),
                     comment="; ".join(f"{p['kind']}={p['value']}" for p in preferences)[:500] or None)
    return {"intake": {**intake.model_dump(), "method": method}, "preferences": preferences}


async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    intake = IntakeResult.model_validate({k: v for k, v in state["intake"].items() if k != "method"})
    focus = research_focus(intake, state["client_id"])
    market = state["market"]
    async with ctx.step("research", input={"question": intake.research_question, "tickers": focus,
                                           "market": market,
                                           "sources": MARKETS[market].research_sources}) as step:
        result = await run_research(ctx, intake.research_question, focus, market)
        step.done(f"{len(result.sources)} sources from {len({s.doc_id for s in result.sources})} "
                  f"documents; answer by {result.method}",
                  output={"answer": result.answer, "sources": [s.chunk_id for s in result.sources]},
                  method=result.method)
    return {"research": result.model_dump()}


async def _a2a(ctx, name: str, skill: str, data: dict[str, Any]) -> tuple[dict, dict]:  # noqa: ANN001
    body, info = await registry.ask(ctx.settings, name, skill, data, ctx.a2a_metadata())
    for call in body.get("tool_calls", []):
        await ctx.emit("tool_call", {**call, "via": f"A2A {name}"})
    for call in body.get("llm_calls", []):
        await ctx.emit("llm_call", {**call, "via": f"A2A {name}"})
    return body["result"], info


async def risk_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    s = ctx.settings
    universe = tickers(state["market"])
    async with ctx.step("risk", input={"market": state["market"], "tickers": len(universe),
                                       "window": [s.train_start, s.train_end]}) as step:
        result, info = await _a2a(ctx, "risk", "market-risk-profile",
                                  {"tickers": universe, "start": s.train_start, "end": s.train_end})
        step.done(" ".join(result["notes"][:2]), output={"notes": result["notes"]}, a2a=info)
    return {"risk_profile": result, "a2a_calls": [info]}


async def mandate_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    async with ctx.step("mandate", input={"client_id": state["client_id"]}) as step:
        result, info = await _a2a(ctx, "compliance", "extract-mandate-rules",
                                  {"client_id": state["client_id"]})
        rules = MandateRules.model_validate(result["rules"])
        excl = ", ".join(rules.excluded_sectors + rules.excluded_tickers) or "none"
        step.done(f"{rules.holdings} stocks, max {rules.max_weight:.0%} each, sector cap "
                  f"{rules.max_sector_weight:.0%}, volatility <= {rules.max_volatility:.0%}, "
                  f"excluded: {excl}", output=rules.model_dump(), a2a=info, method=result["method"])
    return {"rules": rules.model_dump(), "a2a_calls": [info],
            "mandate_meta": {k: result[k] for k in ("method", "notes", "retrieved_chunks", "searches")}}


async def optimize_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    rules, applied = effective_rules(MandateRules.model_validate(state["rules"]),
                                     state.get("preferences") or [], state.get("feedback") or [])
    attempts = state.get("attempts", 0) + 1
    override = None
    if attempts > 1 and state.get("optimization"):
        override = state["optimization"]["problem"]["risk_aversion"] * 2
    problem = build_problem(state["risk_profile"], rules, override)
    async with ctx.step("optimize", input={"qubits": len(problem["tickers"]), "k": problem["k"],
                                           "risk_aversion": problem["risk_aversion"],
                                           "methods": state["methods"],
                                           "advisor_changes": applied["sources"]}) as step:
        result = await run_optimizer(ctx, problem, state["methods"])
        rec = result["proposals"][result["recommended"]]
        q = ""
        if "quantum_gap" in result:
            q = (" Quantum matched the optimum." if result["quantum_found_optimum"]
                 else f" Quantum gap {result['quantum_gap']:.1%}.")
        learned = f" Applied: {', '.join(applied['sources'])}." if applied["sources"] else ""
        step.done(f"{len(problem['tickers'])} qubits; picked {', '.join(rec['selected'])} "
                  f"({result['recommended']}).{q}{learned}", output={
                      "recommended": result["recommended"],
                      "utilities": {m: p["utility"] for m, p in result["proposals"].items()},
                      "quantum_gap": result.get("quantum_gap")})
    result["problem_full"] = problem
    # a new optimization invalidates everything downstream of it
    return {"optimization": result, "attempts": attempts, "backtest": None, "compliance": None,
            "risk_check": None, "applied": applied, "effective_rules": rules.model_dump()}


def _weights(state: dict[str, Any], method: str) -> dict[str, float]:
    return state["optimization"]["proposals"][method]["weights"]


async def backtest_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    market = MARKETS[state["market"]]
    opt = state["optimization"]
    portfolios = {"recommended": _weights(state, opt["recommended"])}
    for method in opt["proposals"]:
        portfolios[method] = _weights(state, method)
    allowed = opt["problem_full"]["tickers"]
    portfolios["equal_weight"] = {t: 1 / len(allowed) for t in allowed}
    current = store.account(state["client_id"])["positions"]
    frame = store.prices(market.code)
    at_train_end = frame.loc[:ctx.settings.train_end].iloc[-1]
    values = {t: n * float(at_train_end[t]) for t, n in current.items()}
    portfolios["current"] = {t: v / sum(values.values()) for t, v in values.items()}
    portfolios["benchmark"] = {market.benchmark: 1.0}
    async with ctx.step("backtest", input={"portfolios": list(portfolios),
                                           "after": ctx.settings.train_end}) as step:
        result = await ctx.toolbox("optimizer_agent").call(
            "optimizer", "run_backtest", portfolios=portfolios, start_after=ctx.settings.train_end,
            risk_free=market.risk_free_rate, market=market.code)
        result["benchmark_name"] = market.benchmark_name
        m = result["metrics"]
        step.done(f"{result['days']} days out of sample: recommended {m['recommended']['total_return']:.1%}, "
                  f"{market.benchmark_name} {m['benchmark']['total_return']:.1%}, "
                  f"current {m['current']['total_return']:.1%}", output=m)
    return {"backtest": result}


async def check_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    opt = state["optimization"]
    rec = opt["proposals"][opt["recommended"]]
    rules = state.get("effective_rules") or state["rules"]
    s = ctx.settings
    async with ctx.step("check", input={"method": opt["recommended"], "weights": rec["weights"]}) as step:
        (compliance, c_info), (risk, r_info) = await asyncio.gather(
            _a2a(ctx, "compliance", "check-portfolio",
                 {"rules": rules, "weights": rec["weights"], "volatility": rec["volatility"]}),
            _a2a(ctx, "risk", "portfolio-risk-check",
                 {"weights": rec["weights"], "start": s.train_start, "end": s.train_end,
                  "max_volatility": rules["max_volatility"]}),
        )
        passed = sum(c["passed"] for c in compliance["checks"])
        step.done(f"{passed}/{len(compliance['checks'])} rules pass"
                  + ("" if compliance["passed"] else " - BLOCKED"), output=compliance,
                  risk_warnings=risk["warnings"])
        if not compliance["passed"]:
            step.observation.update(level="WARNING", status_message="portfolio fails a rule")
    return {"compliance": compliance, "risk_check": risk, "a2a_calls": [c_info, r_info]}


def memo_facts(state: dict[str, Any]) -> dict[str, Any]:
    opt = state["optimization"]
    rec = opt["proposals"][opt["recommended"]]
    account = store.account(state["client_id"])
    market = MARKETS[state["market"]]
    bt = state["backtest"]["metrics"]
    q = opt.get("quantum") or {}
    applied = state.get("applied") or {}
    facts = {
        "client": {"id": state["client_id"], "name": account["name"], "profile": account["profile"],
                   "market": market.name, "currency": market.currency},
        "window": f"prices from {state['risk_profile']['window']['start']} to {state['risk_profile']['window']['end']}",
        "recommended": {"method": opt["recommended"], "label": rec["label"], "k": len(rec["selected"]),
                        "weights": {t: round(w, 4) for t, w in rec["weights"].items()},
                        "expected_return": rec["expected_return"], "volatility": rec["volatility"]},
        "comparison": {m: {"label": p["label"], "utility": round(p["utility"], 6),
                           "seconds": round(p["seconds"], 2), "selected": p["selected"]}
                       for m, p in opt["proposals"].items()},
        "changes": changes(state["client_id"], rec["weights"]),
        "backtest": {"days": state["backtest"]["days"], "recommended": bt.get("recommended"),
                     "benchmark_name": market.benchmark_name,
                     "benchmark_return": bt["benchmark"]["total_return"],
                     "current_return": bt["current"]["total_return"]},
        "compliance": state["compliance"],
        "risk_warnings": state["risk_check"]["warnings"],
        "research": {"question": state["research"]["question"], "answer": state["research"]["answer"],
                     "risk_flags": state["research"]["risk_flags"]},
        "quantum": {"ran": "quantum" in opt, "qubits": opt.get("qubits"),
                    "found_optimum": opt.get("quantum_found_optimum", False),
                    "gap": opt.get("quantum_gap", 0.0),
                    "seconds": opt["proposals"].get("quantum", {}).get("seconds", q.get("execution_time", 0.0)),
                    "classical_seconds": opt["proposals"]["classical"]["seconds"],
                    "mixer": q.get("mixer"), "reps": q.get("reps")},
    }
    # only when something was applied, so the writer cannot claim preferences that do not exist
    if applied.get("sources") or applied.get("notes"):
        facts["advisor_preferences"] = {"applied": applied.get("sources", []), "notes": applied.get("notes", [])}
    return facts


async def report_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    facts = memo_facts(state)
    async with ctx.step("report", input={"facts": list(facts)}) as step:
        memo, method = await run_report(ctx, facts)
        step.done(memo.headline, output=memo.model_dump(), method=method)
    return {"memo": {**memo.model_dump(), "method": method}, "memo_facts": facts}


async def evaluate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Fast checks now; the RAGAS judge runs in the background so the advisor does not wait."""
    ctx = get_context(state["run_id"])
    async with ctx.step("evaluate", input={"question": state["research"]["question"]}) as step:
        scores = deterministic_scores(ctx.settings, state)
        for name, score in scores.items():
            ctx.tracer.score(trace_id=ctx.trace_id, name=name, value=score["value"],
                             comment=score.get("comment"), metadata={"source": score["source"],
                                                                     "run_id": state["run_id"]})
        background = ctx.spawn is not None and ctx.settings.online_evaluation
        parent = ctx.tracer.current_observation_id()
        if background:
            snapshot = {k: state[k] for k in ("research", "memo", "memo_facts")}
            ctx.spawn(_ragas_in_background(ctx, snapshot, parent, state.get("revision", 0)))
        step.done(f"{len(scores)} checks done" + ("; RAGAS quality scoring continues in the background"
                                                  if background else ""),
                  output={k: round(v["value"], 4) for k, v in scores.items()})
    return {"evaluation": {"scores": scores, "judge": None, "notes": [], "revision": state.get("revision", 0),
                           "ragas_status": "running" if background else "off"}}


async def _ragas_in_background(ctx, state: dict[str, Any], parent_span_id: str | None,  # noqa: ANN001
                               revision: int) -> dict[str, Any]:
    """Returns the update the run service merges into the run's evaluation when it finishes."""
    run_id = ctx.run_id
    trace_context = {"trace_id": ctx.trace_id, "parent_span_id": parent_span_id} if ctx.trace_id else None
    with ctx.tracer.section("09b RAGAS quality scoring (background)", as_type="evaluator",
                            input={"question": state["research"]["question"]},
                            trace_context=trace_context) as obs:
        scores, judge, notes = await llm_scores(ctx.settings, state)
        for name, score in scores.items():
            ctx.tracer.score(trace_id=ctx.trace_id, name=name, value=score["value"],
                             comment=(score.get("comment") or "")[:500] or None,
                             metadata={"source": "ragas", "run_id": run_id})
        obs.update(output={k: round(v["value"], 4) for k, v in scores.items()}, metadata={"notes": notes})
    return {"scores": scores, "judge": judge, "notes": notes, "ragas_status": "done", "revision": revision}


async def trades_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    opt = state["optimization"]
    weights = opt["proposals"][opt["recommended"]]["weights"]
    async with ctx.step("trades", input={"target": weights}) as step:
        preview = await ctx.toolbox("trader_agent").call(
            "broker", "preview_rebalance", client_id=state["client_id"], target_weights=weights)
        buys = sum(t["side"] == "buy" for t in preview["trades"])
        step.done(f"{len(preview['trades'])} orders ({buys} buys, {len(preview['trades']) - buys} sells), "
                  f"turnover {preview['turnover']:.0%}", output=preview)
    return {"trades": preview}


async def approval_node(state: dict[str, Any]) -> dict[str, Any]:
    # interrupt() pauses the graph here (checkpointed); the API resumes it with the decision
    decision = interrupt({"run_id": state["run_id"], "trades": state["trades"]["trades"]})
    ctx = get_context(state["run_id"])
    action = decision.get("action") or ("approve" if decision.get("approved") else "reject")
    reviewer = decision.get("reviewer", "advisor")
    async with ctx.step("approval", input=decision) as step:
        if decision.get("remember", True) and ctx.save_preferences:
            rows = feedback_to_preferences(state["client_id"], decision, state["run_id"])
            if rows:
                await ctx.save_preferences(rows)
        revision = state.get("revision", 0)
        if action == "change":
            step.done(f"{reviewer} asked for changes; the agents re-plan", output=decision)
            # clear the proposal so the supervisor re-optimizes with the change
            return {"feedback": [decision], "revision": revision + 1, "attempts": 0, "approval": None,
                    "optimization": None, "backtest": None, "compliance": None, "risk_check": None,
                    "memo": None, "evaluation": None, "trades": None}
        approved = action == "approve"
        ctx.tracer.score(trace_id=ctx.trace_id, name="human_approved", value=1.0 if approved else 0.0,
                         comment=f"{reviewer}: {decision.get('note') or ''}".strip())
        ctx.tracer.score(trace_id=ctx.trace_id, name="human_revisions", value=float(revision))
        step.done(("Approved" if approved else "Rejected") + f" by {reviewer}", output=decision)
    return {"approval": {**decision, "approved": approved, "action": action}}


async def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    async with ctx.step("execute", input={"orders": len(state["trades"]["trades"])}) as step:
        result = await ctx.toolbox("trader_agent").call(
            "broker", "execute_orders", client_id=state["client_id"], trades=state["trades"]["trades"],
            approval_id=state["run_id"], approved_by=state["approval"].get("reviewer", "advisor"))
        cur = MARKETS[state["market"]].symbol
        step.done(f"{len(result['fills'])} paper orders filled; account value "
                  f"{cur}{result['account']['market_value']:,.0f}", output=result)
    return {"execution": result}
