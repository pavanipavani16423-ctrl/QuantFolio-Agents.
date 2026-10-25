"""Human-in-the-loop learning: turn advisor feedback into rules the agents follow.

Two sources, applied the same way:

* this run's feedback - the advisor pressed "Change" on the proposal (remove a stock, cap the
  position size, lower the risk); the supervisor re-plans at once with the change;
* remembered preferences - feedback the advisor chose to keep for this client; they are loaded
  at the start of every later run, so the first proposal already reflects them.

Advisor preferences can only make the mandate stricter (never looser): a removed stock is an
extra exclusion, a cap is min(mandate cap, advisor cap), "lower risk" raises the risk aversion.
"""

from typing import Any

from app.data.universe import BY_TICKER
from app.schemas import MandateRules

RISK_STEP = 1.5  # each "lower risk" request multiplies the risk aversion by this


def feedback_to_preferences(client_id: str, decision: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    """Rows to remember from one review (only when the advisor ticked "remember")."""
    rows = []
    base = {"client_id": client_id, "reason": decision.get("note"), "reviewer": decision.get("reviewer"),
            "run_id": run_id}
    changes = decision.get("changes") or {}
    for ticker in changes.get("remove_tickers") or []:
        rows.append({**base, "kind": "exclude_ticker", "value": ticker})
    if changes.get("max_weight"):
        rows.append({**base, "kind": "max_weight", "value": f"{float(changes['max_weight']):.4f}"})
    if changes.get("lower_risk"):
        rows.append({**base, "kind": "lower_risk", "value": "true"})
    if decision.get("note"):
        rows.append({**base, "kind": "note", "value": decision["note"][:500]})
    return rows


def effective_rules(rules: MandateRules, preferences: list[dict[str, Any]],
                    feedback: list[dict[str, Any]]) -> tuple[MandateRules, dict[str, Any]]:
    """Mandate rules tightened by remembered preferences and this run's feedback.

    Returns (rules to optimize and check against, what was applied - for the UI and trace)."""
    out = rules.model_copy(deep=True)
    applied: dict[str, Any] = {"removed": [], "max_weight": None, "lower_risk": 0, "notes": [],
                               "sources": []}

    def remove(ticker: str, source: str) -> None:
        if ticker in BY_TICKER and ticker not in out.excluded_tickers:
            out.excluded_tickers.append(ticker)
            applied["removed"].append(ticker)
            applied["sources"].append(f"remove {ticker} ({source})")

    def cap(value: float, source: str) -> None:
        if value < out.max_weight:
            out.max_weight = value
            applied["max_weight"] = value
            applied["sources"].append(f"max {value:.0%} per stock ({source})")

    def lower(source: str) -> None:
        out.risk_aversion *= RISK_STEP
        applied["lower_risk"] += 1
        applied["sources"].append(f"lower risk ({source})")

    for pref in preferences:
        kind, value = pref["kind"], pref["value"]
        if kind == "exclude_ticker":
            remove(value, "learned")
        elif kind == "max_weight":
            cap(float(value), "learned")
        elif kind == "lower_risk":
            lower("learned")
        elif kind == "note":
            applied["notes"].append(value)
    for item in feedback:
        changes = item.get("changes") or {}
        for ticker in changes.get("remove_tickers") or []:
            remove(ticker, "this review")
        if changes.get("max_weight"):
            cap(float(changes["max_weight"]), "this review")
        if changes.get("lower_risk"):
            lower("this review")
        if item.get("note"):
            applied["notes"].append(item["note"])

    # keep the problem solvable: enough stocks left, and caps compatible with the holding count
    out.max_weight = max(out.max_weight, 1.0 / out.holdings + 1e-6)
    if out.min_weight * out.holdings > 1:
        out.min_weight = 1.0 / out.holdings
    return out, applied
