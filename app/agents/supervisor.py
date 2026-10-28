"""Supervisor: decides which agent(s) run next from the current state.

Routing is deterministic so every run is reproducible and every decision is explainable:

0. guard                        input rail: personal data, prompt injection, scope policy
                                -> stop here if the request is not allowed
1. intake                       understand the request, recall memory
2. research | risk | mandate    in parallel (one LangGraph superstep)
3. optimize                     exact search (and a rule-of-thumb baseline)
4. backtest
5. check                        compliance + risk guardrail (A2A)
   -> if the volatility limit fails: re-optimize once with doubled risk aversion
6. report -> evaluate           memo with output rails (one self-correction), then scores
7. trades                       order limits at the broker -> stop if any fails
8. approval (human-in-the-loop interrupt) -> execute with the signed approval token
"""

from typing import Any

MAX_OPTIMIZE_ATTEMPTS = 2


def decide(state: dict[str, Any]) -> tuple[list[str], str]:
    """Returns (next nodes, reason). An empty list means the run is finished."""

    def missing(key: str) -> bool:
        return state.get(key) is None

    if missing("input_guard"):
        return ["guard"], "start: safety check on the request"
    if state["input_guard"].get("blocked"):
        return [], "stop: the request was stopped by the input guardrails"
    if missing("intake"):
        return ["intake"], "read the request and recall what we remember about the client"
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
    if not all(c["passed"] for c in state["trades"].get("limits", [])):
        return [], "stop: the orders break a broker limit, so they cannot be approved"
    if missing("approval"):
        return ["approval"], "wait for the advisor's approval"
    if state["approval"].get("approved") and missing("execution"):
        return ["execute"], "approved: place the paper trades"
    return [], "done"
