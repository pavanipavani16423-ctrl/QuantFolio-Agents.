"""Report writer agent: the investment memo the advisor approves."""

import json
from typing import Any

from app.data import store
from app.graph.context import RunContext
from app.guardrails import Finding, worst
from app.guardrails.output import apply_fixes, check_memo, feedback
from app.schemas import Memo

SYSTEM = (
    "You are a portfolio manager writing to a client advisor. Use ONLY the facts given in the "
    "JSON. Plain language, short sentences, no hype. Quote numbers exactly as given (percentages "
    "with one decimal); do not compute new ones. When a risk comes from a research source, keep "
    "its [n] citation. Only if the JSON has advisor_guidance, follow it for tone and content as "
    "long as it agrees with the facts; only if it has advisor_preferences, say in one sentence "
    "that the proposal follows them; only if it has previous_reviews, you may refer to the last "
    "one. Use the client's currency. Never promise returns, and end the summary with: Past "
    "performance does not guarantee future results."
)


def current_weights(client_id: str) -> dict[str, float]:
    account = store.account(client_id)
    frame = store.prices(account["market"])
    values = {t: n * float(frame[t].iloc[-1]) for t, n in account["positions"].items()}
    total = sum(values.values()) + account["cash"]
    return {t: v / total for t, v in values.items()}


def changes(client_id: str, target: dict[str, float]) -> list[dict[str, Any]]:
    before = current_weights(client_id)
    rows = []
    for t in sorted(set(before) | set(target)):
        b, a = before.get(t, 0.0), target.get(t, 0.0)
        if abs(a - b) >= 0.005:
            rows.append({"ticker": t, "before": b, "after": a, "change": a - b})
    return sorted(rows, key=lambda r: -abs(r["change"]))


def template_memo(facts: dict[str, Any]) -> Memo:
    rec = facts["recommended"]
    comp = facts["compliance"]
    n_rules = len(comp["checks"])
    passed = sum(c["passed"] for c in comp["checks"])
    bt = facts["backtest"]
    moves = []
    for c in facts["changes"][:6]:
        verb = "Buy" if c["change"] > 0 else "Sell"
        moves.append(f"{verb} {c['ticker']}: {c['before']:.1%} -> {c['after']:.1%}")
    risks = [f"{f['ticker']}: {f['risk']} [{f['source']}]" for f in facts["research"]["risk_flags"][:3]]
    risks += facts["risk_warnings"][:2]
    if not risks:
        risks = ["Concentration in a small number of large companies."]
    oos = bt.get("recommended") or {}
    summary = (
        f"We recommend holding {rec['k']} stocks, the best combination found by searching "
        f"{facts['selection']['combinations_text']}. "
        f"Based on {facts['window']}, the expected annual return is {rec['expected_return']:.1%} with "
        f"expected volatility of {rec['volatility']:.1%}. "
        f"In the {bt.get('days', 0)} trading days after that window (not used to build the portfolio) "
        f"it returned {oos.get('total_return', 0):.1%}, versus {bt.get('benchmark_return', 0):.1%} for the "
        f"{bt.get('benchmark_name', 'market')}. "
        f"{passed} of {n_rules} mandate rules pass. Past performance does not guarantee future results."
    )
    headline = (f"Rebalance {facts['client']['name']} into {rec['k']} stocks: "
                f"{rec['expected_return']:.1%} expected return at {rec['volatility']:.1%} volatility.")
    return Memo(headline=headline, summary=summary, key_changes=moves or ["No material changes."],
                risks=risks)


async def run_report(ctx: RunContext, facts: dict[str, Any],
                     critique: str | None = None, previous: Memo | None = None) -> tuple[Memo, str]:
    from app.agents.research import normalize_citations

    user = json.dumps(facts, default=str, indent=1)[:12000]
    if critique and previous is not None:
        user += f"\n\nYour previous draft:\n{previous.model_dump_json()}\n\n{critique}"
    memo, method = await ctx.llm.structured("report_writer_revision" if critique else "report_writer",
                                            Memo, SYSTEM, user, fallback=lambda: template_memo(facts))
    memo.risks = [normalize_citations(r) for r in memo.risks]
    memo.summary = normalize_citations(memo.summary)
    return memo, method


async def write_checked_memo(ctx: RunContext, facts: dict[str, Any],
                             valid_sources: set[int]) -> tuple[Memo, str, list[dict], int]:
    """Draft -> output guardrails -> (one revision with the findings) -> template if still failing."""
    memo, method = await run_report(ctx, facts)
    findings = check_memo(memo.model_dump(), facts, valid_sources)
    corrections = 0
    if method == "llm" and worst(findings) == "block":
        corrections = 1
        revised, method2 = await run_report(ctx, facts, critique=feedback(findings), previous=memo)
        revised_findings = check_memo(revised.model_dump(), facts, valid_sources)
        if method2 == "llm" and worst(revised_findings) != "block":
            fixed = {f.check for f in findings if f.verdict == "block"}
            memo, findings = revised, [Finding(f.layer, f.check, "fixed", f"fixed on the second draft: {f.detail}")
                                       if f.check in fixed and f.verdict == "pass" else f for f in revised_findings]
        else:
            memo, method = template_memo(facts), "template_after_guardrail"
            findings = [*check_memo(memo.model_dump(), facts, valid_sources),
                        Finding("output", "memo_fallback", "fixed",
                                "the model's drafts failed the checks; used the fact-based template")]
    memo = Memo.model_validate(apply_fixes(memo.model_dump(), findings))
    return memo, method, [f.to_dict() for f in findings], corrections
