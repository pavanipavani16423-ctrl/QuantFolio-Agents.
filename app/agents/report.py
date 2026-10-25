"""Report writer agent: the investment memo the advisor approves."""

import json
from typing import Any

from app.data import store
from app.graph.context import RunContext
from app.schemas import Memo

SYSTEM = (
    "You are a portfolio manager writing to a client advisor. Use ONLY the facts given in the "
    "JSON. Plain language, short sentences, no hype. Mention numbers as given (percentages "
    "with one decimal). When a risk comes from a research source, keep its [n] citation. "
    "Say clearly that the quantum optimizer ran on a simulator and whether it matched the "
    "classical optimum. Never promise returns; past performance does not guarantee results."
)


def current_weights(client_id: str) -> dict[str, float]:
    account = store.account(client_id)
    frame = store.prices()
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
        risks = ["Concentration in a small number of large US stocks."]
    q = facts["quantum"]
    if q.get("ran"):
        if q["found_optimum"]:
            qnote = (f"The quantum optimizer (QAOA, {q['qubits']} simulated qubits) chose the same "
                     f"{rec['k']} stocks as the exact classical search; it took {q['seconds']:.1f} s "
                     f"versus {q['classical_seconds']:.2f} s.")
        else:
            qnote = (f"The quantum optimizer (QAOA, {q['qubits']} simulated qubits) came within "
                     f"{q['gap']:.1%} of the classical optimum; the hybrid step closed the gap.")
    else:
        qnote = "The quantum optimizer was not run for this request."
    oos = bt.get("recommended") or {}
    summary = (
        f"We recommend holding {rec['k']} stocks chosen by the {rec['label'].lower()}. "
        f"Based on {facts['window']}, the expected annual return is {rec['expected_return']:.1%} with "
        f"expected volatility of {rec['volatility']:.1%}. "
        f"In the {bt.get('days', 0)} trading days after that window (not used to build the portfolio) "
        f"it returned {oos.get('total_return', 0):.1%}, versus {bt.get('spy_return', 0):.1%} for SPY. "
        f"{passed} of {n_rules} mandate rules pass. Past performance does not guarantee future results."
    )
    headline = (f"Rebalance {facts['client']['name']} into {rec['k']} stocks: "
                f"{rec['expected_return']:.1%} expected return at {rec['volatility']:.1%} volatility.")
    return Memo(headline=headline, summary=summary, key_changes=moves or ["No material changes."],
                risks=risks, quantum_note=qnote)


async def run_report(ctx: RunContext, facts: dict[str, Any]) -> tuple[Memo, str]:
    return await ctx.llm.structured("report_writer", Memo, SYSTEM,
                                    json.dumps(facts, default=str, indent=1)[:12000],
                                    fallback=lambda: template_memo(facts))
