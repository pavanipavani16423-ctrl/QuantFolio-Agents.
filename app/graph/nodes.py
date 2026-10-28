"""LangGraph nodes: one per agent step. Each node is a thin wrapper that

* looks up the run's dependencies (`RunContext`),
* opens its numbered step (Langfuse section + UI event),
* calls the agent / A2A service / MCP tools, and returns only the state keys it owns.

Guardrail findings are returned under `guardrails` (a list that accumulates over the run),
each tagged with the step and the proposal revision it belongs to.
"""

import asyncio
import math
from typing import Any

from langgraph.types import interrupt

from app.a2a import registry
from app.agents import supervisor
from app.agents.intake import research_focus, run_intake
from app.agents.optimizer import build_problem, run_optimizer
from app.agents.preferences import effective_rules, feedback_to_preferences
from app.agents.report import changes, write_checked_memo
from app.agents.research import run_research
from app.data import store
from app.data.universe import MARKETS, tickers
from app.evaluation.online import deterministic_scores, llm_scores
from app.graph.context import get_context
from app.guardrails.input import check_request
from app.memory import MemoryManager
from app.schemas import IntakeResult, MandateRules, ResearchResult
from app.security import approvals


def _tag(findings: list[dict[str, Any]], step: str, revision: int = 0) -> list[dict[str, Any]]:
    return [{**f, "step": step, "revision": revision} for f in findings]


def _blocking(findings: list[dict[str, Any]]) -> int:
    return sum(f["verdict"] == "block" for f in findings)


async def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    nodes, reason = supervisor.decide(state)
    await ctx.emit("decision", {"next": nodes, "reason": reason})
    return {"route": nodes, "decisions": [{"next": nodes, "reason": reason}]}


def route(state: dict[str, Any]) -> list[str] | str:
    return state["route"] or "__end__"


async def guard_node(state: dict[str, Any]) -> dict[str, Any]:
    """Input rail: nothing else runs on a request that fails it."""
    ctx = get_context(state["run_id"])
    s = ctx.settings
    async with ctx.step("guard", input={"request": state["request"]}) as step:
        if s.guardrails_enabled:
            verdict, findings = check_request(state["request"], state["market"], state.get("pii") or {},
                                              s.injection_block_threshold, s.semantic_injection_threshold)
        else:
            verdict, findings = "pass", []
        items = [f.to_dict() for f in findings]
        blocked = [f for f in items if f["verdict"] == "block"]
        reason = "; ".join(f["detail"] for f in blocked)
        step.done(f"Stopped: {reason}" if blocked else
                  "Request is safe: " + ", ".join(f"{f['check'].replace('_', ' ')} {f['verdict']}" for f in items),
                  output=items, verdict=verdict)
        if blocked:
            step.observation.update(level="WARNING", status_message=reason[:300])
    ctx.tracer.score(trace_id=ctx.trace_id, name="guardrail_input_blocked", value=1.0 if blocked else 0.0,
                     comment=reason[:500] or None)
    ctx.tracer.score(trace_id=ctx.trace_id, name="guardrail_pii_redacted",
                     value=float(sum((state.get("pii") or {}).values())))
    if blocked:
        await ctx.record("request_blocked", client_id=state["client_id"],
                         checks=[f["check"] for f in blocked], reason=reason[:300])
    return {"input_guard": {"verdict": verdict, "blocked": bool(blocked), "reason": reason or None},
            "guardrails": _tag(items, "guard")}


async def intake_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    async with ctx.step("intake", input={"request": state["request"],
                                         "client_id": state["client_id"]}) as step:
        intake, method = await run_intake(ctx, state["request"], state["client_id"])
        memory = await ctx.memory.recall(state["client_id"]) if ctx.memory else {}
        preferences = MemoryManager.preferences(memory)
        counts = {layer: len(memory.get(layer, [])) for layer in ("episodic", "semantic", "procedural")}
        recalled = sum(counts.values())
        learned = (f" Remembered {recalled} item(s): {counts['episodic']} past review(s), "
                   f"{counts['semantic']} preference(s), {counts['procedural']} note(s).") if recalled else ""
        step.done(f"Question: {intake.research_question}.{learned}", output=intake.model_dump(),
                  method=method, memory=counts)
    ctx.tracer.score(trace_id=ctx.trace_id, name="learned_preferences_applied",
                     value=float(counts.get("semantic", 0)),
                     comment="; ".join(f"{p['kind']}={p['value']}" for p in memory.get("semantic", []))[:500] or None)
    ctx.tracer.score(trace_id=ctx.trace_id, name="memory_items_recalled", value=float(recalled))
    return {"intake": {**intake.model_dump(), "method": method}, "preferences": preferences,
            "memory": {**memory, "counts": counts},
            "guardrails": _tag(memory.get("quarantined", []), "intake")}


async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    intake = IntakeResult.model_validate({k: v for k, v in state["intake"].items() if k != "method"})
    focus = research_focus(intake, state["client_id"])
    market = state["market"]
    async with ctx.step("research", input={"question": intake.research_question, "tickers": focus,
                                           "market": market,
                                           "sources": MARKETS[market].research_sources}) as step:
        cached = await ctx.memory.cached_research(market, focus, intake.research_question) if ctx.memory else None
        if cached:
            result = ResearchResult.model_validate(cached["result"])
            result.cache = {k: cached[k] for k in ("similarity", "question", "run_id", "when")}
            result.method = "memory"
            summary = (f"Reused a checked answer from memory (asked {cached['when']}, similarity "
                       f"{cached['similarity']:.2f}); {len(result.sources)} sources")
        else:
            result = await run_research(ctx, intake.research_question, focus, market)
            if ctx.memory and result.method == "llm" and not _blocking(result.guardrails):
                await ctx.memory.cache_research(market, focus, intake.research_question,
                                                result.model_dump(exclude={"cache"}), state["run_id"])
            summary = (f"{len(result.sources)} sources from {len({s.doc_id for s in result.sources})} "
                       f"documents; answer by {result.method}"
                       + (f"; {len(result.quarantined)} passage(s) quarantined" if result.quarantined else "")
                       + ("; revised once after the checks" if result.self_corrections else ""))
        step.done(summary, output={"answer": result.answer, "sources": [s.chunk_id for s in result.sources]},
                  method=result.method, guardrails=result.guardrails)
    ctx.tracer.score(trace_id=ctx.trace_id, name="research_cache_hit", value=1.0 if cached else 0.0)
    ctx.tracer.score(trace_id=ctx.trace_id, name="guardrail_quarantined_passages",
                     value=float(len(result.quarantined)))
    return {"research": result.model_dump(),
            "guardrails": [] if cached else _tag(result.guardrails, "research")}


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
    held = result.get("quarantined") or []
    findings = [{"layer": "retrieval", "check": "mandate_injection", "verdict": "fixed" if held else "pass",
                 "detail": (f"{len(held)} policy passage(s) quarantined" if held
                            else f"{len(result['retrieved_chunks'])} policy passages scanned, none quarantined")}]
    return {"rules": rules.model_dump(), "a2a_calls": [info],
            "mandate_meta": {k: result.get(k) for k in ("method", "notes", "retrieved_chunks", "searches",
                                                         "quarantined")},
            "guardrails": _tag(findings, "mandate")}


async def optimize_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    mandate = MandateRules.model_validate(state["rules"])
    attempts = state.get("attempts", 0) + 1
    override = None
    if attempts > 1 and state.get("optimization"):
        override = state["optimization"]["problem"]["risk_aversion"] * 2
    # advisor exclusions must leave enough stocks to hold: if they do not, drop the remembered
    # ones first, then this review's, and say so (never fail every future run for the client)
    findings: list[dict[str, Any]] = []
    for prefs, feedback, note in ((state.get("preferences") or [], state.get("feedback") or [], None),  # noqa: B007 - `note` of the feasible option is read after the loop
                                  ([], state.get("feedback") or [], "remembered exclusions ignored"),
                                  ([], [], "advisor exclusions ignored")):
        rules, applied = effective_rules(mandate, prefs, feedback)
        problem = build_problem(state["risk_profile"], rules, override)
        if len(problem["tickers"]) >= problem["k"]:
            break
    else:
        raise RuntimeError(f"the mandate leaves {len(problem['tickers'])} stocks but requires {problem['k']}")
    if note:
        findings.append({"layer": "memory", "check": "preferences_feasible", "verdict": "warn",
                         "detail": f"{note}: they left fewer than {problem['k']} allowed stocks"})
    combos = math.comb(len(problem["tickers"]), problem["k"]) if problem["k"] <= len(problem["tickers"]) else 0
    async with ctx.step("optimize", input={"allowed_stocks": len(problem["tickers"]), "k": problem["k"],
                                           "combinations": combos,
                                           "risk_aversion": problem["risk_aversion"],
                                           "advisor_changes": applied["sources"]}) as step:
        result = await run_optimizer(ctx, problem)
        rec = result["proposals"][result["recommended"]]
        learned = f" Applied: {', '.join(applied['sources'])}." if applied["sources"] else ""
        gap = result.get("baseline_gap")
        base = f" The rule of thumb falls {gap:.1%} short." if gap else ""
        step.done(f"Searched {combos:,} combinations of {len(problem['tickers'])} allowed stocks; picked "
                  f"{', '.join(rec['selected'])}.{base}{learned}", output={
                      "recommended": result["recommended"],
                      "utilities": {m: p["utility"] for m, p in result["proposals"].items()}})
    result["problem_full"] = problem
    result["combinations"] = combos
    # a new optimization invalidates everything downstream of it
    return {"optimization": result, "attempts": attempts, "backtest": None, "compliance": None,
            "risk_check": None, "applied": applied, "effective_rules": rules.model_dump(),
            "guardrails": _tag(findings, "optimize", state.get("revision", 0))}


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
    applied = state.get("applied") or {}
    memory = state.get("memory") or {}
    combos = opt.get("combinations") or 0
    search = opt.get("search") or {}
    rec_return = (bt.get("recommended") or {}).get("total_return")
    facts = {
        "client": {"id": state["client_id"], "name": account["name"], "profile": account["profile"],
                   "market": market.name, "currency": market.currency},
        "window": f"prices from {state['risk_profile']['window']['start']} to {state['risk_profile']['window']['end']}",
        "recommended": {"method": opt["recommended"], "label": rec["label"], "k": len(rec["selected"]),
                        "weights": {t: round(w, 4) for t, w in rec["weights"].items()},
                        "expected_return": rec["expected_return"], "volatility": rec["volatility"]},
        "selection": {"allowed_stocks": len(opt["problem_full"]["tickers"]), "combinations": combos,
                      "combinations_text": (f"all {combos:,} possible combinations" if search.get("subsets_evaluated")
                                            else f"the {len(opt['problem_full']['tickers'])} allowed stocks"),
                      "optimality": search.get("optimality"),
                      "rule_of_thumb_shortfall": opt.get("baseline_gap")},
        "changes": changes(state["client_id"], rec["weights"]),
        "backtest": {"days": state["backtest"]["days"], "recommended": bt.get("recommended"),
                     "benchmark_name": market.benchmark_name,
                     "benchmark_return": bt["benchmark"]["total_return"],
                     "current_return": bt["current"]["total_return"],
                     "difference_vs_benchmark": (rec_return - bt["benchmark"]["total_return"])
                     if rec_return is not None else None},
        "compliance": state["compliance"],
        "risk_warnings": state["risk_check"]["warnings"],
        "research": {"question": state["research"]["question"], "answer": state["research"]["answer"],
                     "risk_flags": state["research"]["risk_flags"]},
    }
    # only when present, so the writer cannot claim memory or preferences that do not exist
    if applied.get("sources"):
        facts["advisor_preferences"] = {"applied": applied["sources"]}
    notes = [n["value"] for n in memory.get("procedural", [])] + [
        n for n in applied.get("notes", []) if n not in {p["value"] for p in memory.get("procedural", [])}]
    if notes:
        facts["advisor_guidance"] = notes[-5:]
    if memory.get("episodic"):
        facts["previous_reviews"] = [f"{e['when']}: {e['summary']}" for e in memory["episodic"]]
    return facts


async def report_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    facts = memo_facts(state)
    valid = {s["n"] for s in state["research"]["sources"]}
    revision = state.get("revision", 0)
    async with ctx.step("report", input={"facts": list(facts)}) as step:
        memo, method, findings, corrections = await write_checked_memo(ctx, facts, valid)
        fixed = [f for f in findings if f["verdict"] == "fixed"]
        step.done(memo.headline + (f" ({len(fixed)} check(s) fixed)" if fixed else ""),
                  output=memo.model_dump(), method=method, guardrails=findings)
    ctx.tracer.score(trace_id=ctx.trace_id, name="guardrail_output_violations",
                     value=float(sum(f["verdict"] in ("fixed", "block") and f["check"] != "memo_disclaimer"
                                     for f in findings)))
    ctx.tracer.score(trace_id=ctx.trace_id, name="self_corrections",
                     value=float(corrections + state["research"].get("self_corrections", 0)))
    return {"memo": {**memo.model_dump(), "method": method, "self_corrections": corrections},
            "memo_facts": facts, "guardrails": _tag(findings, "report", revision)}


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
    with ctx.tracer.section("10b RAGAS quality scoring (background)", as_type="evaluator",
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
    revision = state.get("revision", 0)
    async with ctx.step("trades", input={"target": weights}) as step:
        preview = await ctx.toolbox("trader_agent").call(
            "broker", "preview_rebalance", client_id=state["client_id"], target_weights=weights)
        buys = sum(t["side"] == "buy" for t in preview["trades"])
        failed = [c for c in preview["limits"] if not c["passed"]]
        step.done(f"{len(preview['trades'])} orders ({buys} buys, {len(preview['trades']) - buys} sells), "
                  f"turnover {preview['turnover']:.0%}; "
                  + ("order limits: " + "; ".join(c["detail"] for c in failed) if failed
                     else f"all {len(preview['limits'])} order limits pass"), output=preview)
        if failed:
            step.observation.update(level="WARNING", status_message="order limits failed")
    findings = [{"layer": "action", "check": c["check"], "verdict": "pass" if c["passed"] else "block",
                 "detail": c["detail"]} for c in preview["limits"]]
    return {"trades": preview, "guardrails": _tag(findings, "trades", revision)}


async def approval_node(state: dict[str, Any]) -> dict[str, Any]:
    # interrupt() pauses the graph here (checkpointed); the API resumes it with the decision
    decision = interrupt({"run_id": state["run_id"], "trades": state["trades"]["trades"]})
    ctx = get_context(state["run_id"])
    action = decision.get("action") or ("approve" if decision.get("approved") else "reject")
    reviewer = decision.get("reviewer") or "advisor"
    client_id = state["client_id"]
    revision = state.get("revision", 0)
    findings: list[dict[str, Any]] = []
    if decision.get("note") and ctx.memory:
        # the note feeds this run's memo guidance and later runs: an instruction attack is withheld
        safe, finding = ctx.memory.screen_note(decision["note"])
        if safe is None:
            decision = {**decision, "note": None, "note_withheld": True}
            findings.append(finding.to_dict())
    async with ctx.step("approval", input={k: v for k, v in decision.items() if k != "approval_token"}) as step:
        if decision.get("remember", True) and ctx.memory:
            rows = feedback_to_preferences(client_id, decision, state["run_id"])
            if rows:
                findings += [f.to_dict() for f in await ctx.memory.remember_preferences(rows)]
        outcome = {"change": "changed", "approve": "approved", "reject": "rejected"}[action]
        if ctx.memory:
            await ctx.memory.remember_episode(client_id, state["run_id"], outcome, state, decision)
        if action == "change":
            await ctx.record("change_requested", actor=reviewer, client_id=client_id, revision=revision,
                             changes=decision.get("changes"), note=decision.get("note"))
            step.done(f"{reviewer} asked for changes; the agents re-plan", output=decision)
            # clear the proposal so the supervisor re-optimizes with the change
            return {"feedback": [decision], "revision": revision + 1, "attempts": 0, "approval": None,
                    "optimization": None, "backtest": None, "compliance": None, "risk_check": None,
                    "memo": None, "evaluation": None, "trades": None,
                    "guardrails": _tag(findings, "approval", revision)}
        approved = action == "approve"
        token = None
        trades = state["trades"]["trades"]
        if approved:
            token = approvals.issue(state["run_id"], client_id, reviewer, trades, ctx.settings.approval_ttl_seconds)
            findings.append({"layer": "action", "check": "approval_token", "verdict": "pass",
                             "detail": f"signed, single-use token for {len(trades)} orders issued to {reviewer}"})
        await ctx.record("approved" if approved else "rejected", actor=reviewer, client_id=client_id,
                         revision=revision, orders=len(trades), note=decision.get("note"),
                         orders_hash=approvals.orders_hash(trades))
        ctx.tracer.score(trace_id=ctx.trace_id, name="human_approved", value=1.0 if approved else 0.0,
                         comment=f"{reviewer}: {decision.get('note') or ''}".strip())
        ctx.tracer.score(trace_id=ctx.trace_id, name="human_revisions", value=float(revision))
        step.done(("Approved" if approved else "Rejected") + f" by {reviewer}", output=decision)
    return {"approval": {**decision, "approved": approved, "action": action}, "approval_token": token,
            "guardrails": _tag(findings, "approval", revision)}


async def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    ctx = get_context(state["run_id"])
    async with ctx.step("execute", input={"orders": len(state["trades"]["trades"])}) as step:
        result = await ctx.toolbox("trader_agent").call(
            "broker", "execute_orders", client_id=state["client_id"], trades=state["trades"]["trades"],
            approval_token=state["approval_token"])
        cur = MARKETS[state["market"]].symbol
        step.done(f"{len(result['fills'])} paper orders filled; account value "
                  f"{cur}{result['account']['market_value']:,.0f}", output=result)
    await ctx.record("orders_executed", actor="trader_agent", client_id=state["client_id"],
                     fills=len(result["fills"]), approved_by=result.get("approved_by"),
                     token_id=result.get("approval_id"))
    return {"execution": result, "approval_token": None}
