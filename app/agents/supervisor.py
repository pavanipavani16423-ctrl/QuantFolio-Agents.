"""Supervisor: decides which agent(s) run next from the current state.

Routing is deterministic so every run is reproducible and every decision is explainable:

1. intake                       understand the request
2. research | risk | mandate    in parallel (one LangGraph superstep)
3. optimize                     classical vs quantum vs hybrid
4. backtest
5. check                        compliance + risk guardrail (A2A)
   -> if the volatility limit fails: re-optimize once with doubled risk aversion
6. report -> evaluate
7. trades -> approval (human-in-the-loop interrupt) -> execute
"""

from typing import Any

MAX_OPTIMIZE_ATTEMPTS = 2


def decide(state: dict[str, Any]) -> tuple[list[str], str]:
    """Returns (next nodes, reason). An empty list means the run is finished."""

    def missing(key: str) -> bool:
        return state.get(key) is None

    if missing("intake"):
        return ["intake"], "start: read the request"
    pending = [k for k, field in (("research", "research"), ("risk", "risk_profile"),
                                  ("mandate", "rules")) if missing(field)]
    if pending:
        return pending, "gather research, risk and the client's rules in parallel"
    if missing("optimization"):
        return ["optimize"], "all inputs ready: optimize the portfolio"
    if missing("backtest"):
        return ["backtest"], "test the candidate portfolios out of sample"
    if missing("compliance"):
        return ["check"], "check the recommendation against the mandate"
    if not state["compliance"]["passed"] and missing("memo"):
        failed = {c["rule"] for c in state["compliance"]["checks"] if not c["passed"]}
        if failed <= {"max_volatility"} and state.get("attempts", 1) < MAX_OPTIMIZE_ATTEMPTS:
            return ["optimize"], "volatility limit failed: re-optimize with more risk aversion"
    if missing("memo"):
        return ["report"], "write the investment memo"
    if missing("evaluation"):
        return ["evaluate"], "score answer and memo quality"
    if not state["compliance"]["passed"]:
        return [], "stop: the portfolio fails a mandate rule, so no trades are proposed"
    if not state["intake"].get("wants_rebalance", True):
        return [], "research-only request: no trades"
    if missing("trades"):
        return ["trades"], "prepare paper trades"
    if missing("approval"):
        return ["approval"], "wait for the advisor's approval"
    if state["approval"].get("approved") and missing("execution"):
        return ["execute"], "approved: place the paper trades"
    return [], "done"
