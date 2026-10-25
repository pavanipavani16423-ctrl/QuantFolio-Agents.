"""LangGraph state. Parallel branches write different keys; list keys merge with `add`."""

from operator import add
from typing import Annotated, Any, TypedDict


class RunState(TypedDict, total=False):
    run_id: str
    client_id: str
    market: str
    request: str
    methods: list[str]

    # human-in-the-loop learning
    preferences: list[dict[str, Any]]  # remembered from earlier reviews of this client
    feedback: Annotated[list[dict[str, Any]], add]  # "Change" requests in this run
    applied: dict[str, Any]  # what the preferences/feedback changed
    effective_rules: dict[str, Any]  # mandate rules tightened by the above
    revision: int

    intake: dict[str, Any]
    research: dict[str, Any]
    risk_profile: dict[str, Any]
    rules: dict[str, Any]
    mandate_meta: dict[str, Any]
    optimization: dict[str, Any]
    risk_aversion_override: float | None
    backtest: dict[str, Any]
    compliance: dict[str, Any]
    risk_check: dict[str, Any]
    memo: dict[str, Any]
    memo_facts: dict[str, Any]
    evaluation: dict[str, Any]
    trades: dict[str, Any]
    approval: dict[str, Any]
    execution: dict[str, Any]

    route: list[str]
    attempts: int
    blocked: str | None
    decisions: Annotated[list[dict[str, Any]], add]
    a2a_calls: Annotated[list[dict[str, Any]], add]
    warnings: Annotated[list[str], add]
