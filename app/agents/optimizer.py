"""Portfolio optimizer agent: picks the stocks, then the money split, under the mandate.

* optimal  : exhaustive search over every k-subset - the proven optimum of the selection
             problem (local search when the universe is too large)
* baseline : naive rule of thumb (top-k return/risk), kept to show what the search adds

Both go through the same weight step (see `app.quant.portfolio`). The recommendation is the
optimal proposal unless it cannot meet the volatility limit and the baseline can.
"""

from typing import Any

from app.data.universe import BY_TICKER
from app.graph.context import RunContext
from app.schemas import MandateRules, Proposal

LABELS = {
    "optimal": "Best combination (exact search)",
    "baseline": "Simple rule of thumb (baseline)",
}


def build_problem(stats: dict[str, Any], rules: MandateRules, risk_aversion: float | None = None,
                  extra_excluded: list[str] | None = None) -> dict:
    """The selection problem for one client: the market universe in `stats` minus the mandate's
    exclusions and any stocks the advisor removed (learned preferences)."""
    removed = set(rules.excluded_tickers) | set(extra_excluded or [])
    allowed = [BY_TICKER[t] for t in stats["tickers"]
               if BY_TICKER[t].sector not in rules.excluded_sectors and t not in removed]
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


async def run_optimizer(ctx: RunContext, problem: dict) -> dict[str, Any]:
    tools = ctx.toolbox("optimizer_agent")
    out: dict[str, Any] = {"problem": {k: problem[k] for k in ("tickers", "k", "risk_aversion")},
                           "candidates": len(problem["tickers"]), "errors": {}}
    selections = await tools.call("optimizer", "select_stocks", problem=problem)
    out["search"] = selections["optimal"]["details"]

    proposals: dict[str, Proposal] = {}
    for method, sel in selections.items():
        if not sel.get("feasible"):
            out["errors"][method] = "selection does not satisfy the holding count or sector limits"
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
    if "optimal" not in proposals:
        raise RuntimeError("no feasible portfolio: " + "; ".join(out["errors"].values()))
    best = proposals["optimal"]
    if not best.volatility_limit_met and "baseline" in proposals and proposals["baseline"].volatility_limit_met:
        best = proposals["baseline"]
    out["proposals"] = {m: p.model_dump() for m, p in proposals.items()}
    out["recommended"] = best.method
    base = proposals.get("baseline")
    opt = proposals["optimal"]
    if base is not None and abs(opt.utility) > 1e-12:
        # how far the rule of thumb falls short of the best combination (0 = same answer)
        out["baseline_gap"] = max(0.0, (opt.utility - base.utility) / abs(opt.utility))
    return out
