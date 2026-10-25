"""Portfolio optimizer agent: classical vs quantum (QAOA) vs hybrid, on the same problem.

All methods share the selection QUBO and the weight step (see `app.quant.portfolio`), so the
only difference between them is how the k stocks are chosen:

* classical : exhaustive search - the proven optimum of the selection problem
* quantum   : QAOA on the local simulator (XY mixer by default: every sample has exactly k)
* hybrid    : the QAOA answer, repaired if needed and improved by 1-swap local search
* greedy    : naive baseline (top-k return/risk), for reference only

The recommendation is the feasible proposal with the highest final utility; on a tie the
classical one wins (same answer, proven optimal, faster).
"""

import asyncio
from typing import Any

from app.data.universe import UNIVERSE
from app.graph.context import RunContext
from app.schemas import MandateRules, Proposal

LABELS = {
    "classical": "Normal computer (exact search)",
    "quantum": "Quantum computer, simulated (QAOA)",
    "hybrid": "Quantum + classical (hybrid)",
    "greedy": "Simple rule of thumb (baseline)",
}
PRIORITY = {"classical": 0, "hybrid": 1, "quantum": 2, "greedy": 3}


def build_problem(stats: dict[str, Any], rules: MandateRules, risk_aversion: float | None = None) -> dict:
    allowed = [a for a in UNIVERSE if a.sector not in rules.excluded_sectors
               and a.ticker not in rules.excluded_tickers]
    index = {t: i for i, t in enumerate(stats["tickers"])}
    idx = [index[a.ticker] for a in allowed]
    return {
        "tickers": [a.ticker for a in allowed],
        "sectors": [a.sector for a in allowed],
        "mu": [stats["expected_return"][a.ticker] for a in allowed],
        "cov": [[stats["covariance"][i][j] for j in idx] for i in idx],
        "k": int(rules.holdings),
        "risk_aversion": float(risk_aversion or rules.risk_aversion),
        "max_sector_weight": rules.max_sector_weight,
        "min_weight": rules.min_weight,
        "max_weight": rules.max_weight,
        "max_volatility": rules.max_volatility,
    }


async def run_optimizer(ctx: RunContext, problem: dict, methods: list[str]) -> dict[str, Any]:
    tools = ctx.toolbox("optimizer_agent")
    s = ctx.settings
    out: dict[str, Any] = {"problem": {k: problem[k] for k in ("tickers", "k", "risk_aversion")},
                           "qubits": len(problem["tickers"]), "errors": {}}

    async def classical() -> dict:
        return await tools.call("optimizer", "select_classical", problem=problem)

    async def quantum() -> dict:
        return await tools.call("optimizer", "select_quantum", problem=problem, reps=s.qaoa_reps,
                                maxiter=s.qaoa_maxiter, shots=s.qaoa_shots, mixer=s.qaoa_mixer)

    want_quantum = "quantum" in methods or "hybrid" in methods
    tasks = [classical()] + ([quantum()] if want_quantum else [])
    results = await asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(results[0], Exception):
        raise results[0]  # the classical solver is the fallback for everything else
    cls = results[0]
    selections: dict[str, dict] = {
        "classical": {**cls["exact"], "seconds": cls["exact"]["seconds"]},
        "greedy": cls["greedy"],
    }
    out["classical"] = cls["exact"]["details"]
    if want_quantum:
        q = results[1]
        if isinstance(q, Exception):
            out["errors"]["quantum"] = f"{type(q).__name__}: {q}"
        else:
            out["quantum"] = {**q["qaoa"], "convergence": q["convergence"],
                              "top_samples": q["top_samples"]}
            if "quantum" in methods:
                selections["quantum"] = {**q["best"], "seconds": q["seconds"]}
            if "hybrid" in methods:
                try:
                    h = await tools.call("optimizer", "refine_hybrid", problem=problem,
                                         start_bitstring=q["best"]["bitstring"])
                    selections["hybrid"] = {**h, "seconds": q["seconds"] + h["seconds"]}
                    out["hybrid"] = {"swap_moves": h["swap_moves"], "repaired": h["repaired"],
                                     "start_utility": h["start_utility"]}
                except Exception as exc:  # noqa: BLE001
                    out["errors"]["hybrid"] = f"{type(exc).__name__}: {exc}"

    proposals: dict[str, Proposal] = {}
    for method, sel in selections.items():
        if not sel.get("feasible"):
            out["errors"][method] = "selection does not satisfy the cardinality/sector limits"
            continue
        w = await tools.call("optimizer", "optimize_portfolio_weights", problem=problem,
                             selected=sel["selected"])
        proposals[method] = Proposal(
            method=method, label=LABELS[method], selected=sel["selected"], weights=w["weights"],
            expected_return=w["expected_return"], volatility=w["volatility"], utility=w["utility"],
            selection_utility=sel["utility"], seconds=float(sel.get("seconds", 0.0)),
            feasible=True, volatility_limit_met=w["volatility_limit_met"],
            details={"sector_weights": w["sector_weights"], "weight_status": w["status"]},
        )
    candidates = [p for p in proposals.values() if p.method != "greedy" and p.volatility_limit_met]
    candidates = candidates or [p for p in proposals.values() if p.method != "greedy"]
    best = max(candidates, key=lambda p: (round(p.utility, 9), -PRIORITY[p.method]))

    exact_u = selections["classical"]["utility"]
    if "quantum" in selections:
        gap = (exact_u - selections["quantum"]["utility"]) / abs(exact_u) if exact_u else 0.0
        out["quantum_gap"] = max(0.0, gap)
        out["quantum_found_optimum"] = gap <= 1e-9
    out["proposals"] = {m: p.model_dump() for m, p in proposals.items()}
    out["recommended"] = best.method
    return out
