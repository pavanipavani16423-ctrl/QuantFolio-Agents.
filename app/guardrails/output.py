"""Output guardrails for the research answer and the investment memo.

Each check returns a Finding. "block" findings make the writer try again with the findings as
feedback (evaluator-optimizer loop); if the second draft still fails, the deterministic
template memo is used, which is correct by construction. Small, safe fixes (a missing
disclaimer) are applied directly and reported as "fixed".
"""

import json
import re
from typing import Any

from app.data.universe import BY_TICKER
from app.guardrails import Finding

CITATION = re.compile(r"\[(\d+)\]")
PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s?%")
PROMISES = re.compile(
    r"\b(guarantee[sd]?\s+(\w+\s+){0,2}(returns?|profits?|gains?|growth|income|performance|results)|"
    r"(returns?|profits?|gains?|income)\s+(are|is|will\s+be)\s+(guaranteed|assured|certain)|"
    r"guaranteed\s+to\s+\w+|risk[- ]free\s+(returns?|investment|portfolio|profits?)|can(?:no|')t\s+lose|"
    r"sure\s+(thing|bet)|certain\s+to\s+(rise|grow|gain|outperform|beat)|"
    r"will\s+(definitely|certainly|surely)\s+(rise|grow|double|outperform|beat|gain)|"
    r"(returns?|money|investment|portfolio|value|savings|wealth)\s+will\s+(double|triple)|assured\s+returns?)\b", re.I)
# "past performance does not guarantee future results", "there is no guarantee that ..."
NEGATED = re.compile(r"\b(not|no|never|cannot|can't|without|nor)\s+(a\s+|any\s+)?guarantee\w*\s+(\w+\s+){0,2}\w+", re.I)


def find_promise(text: str) -> re.Match | None:
    return PROMISES.search(NEGATED.sub(" ", text))


DISCLAIMER = re.compile(r"past\s+performance\s+(does\s+not|doesn'?t|is\s+not|is\s+no)\s+(guarantee|indicat)", re.I)
DISCLAIMER_TEXT = "Past performance does not guarantee future results."
TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z&]{1,11}\b")
CURRENCY_MARKS = {"USD": re.compile(r"\$|\bUSD\b|\bdollars?\b", re.I), "INR": re.compile(r"₹|\bINR\b|\brupees?\b|\bcrore\b|\blakh\b", re.I)}


def check_research(answer: str, valid_sources: set[int], min_coverage: float = 0.5) -> list[Finding]:
    findings = []
    cited = {int(n) for n in CITATION.findall(answer)}
    bad = sorted(cited - valid_sources)
    findings.append(Finding("output", "research_citations_exist", "block" if bad else "pass",
                            f"cites sources that do not exist: {bad}" if bad else "every [n] points to a retrieved source"))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if len(s) > 15]
    coverage = sum(bool(CITATION.search(s)) for s in sentences) / len(sentences) if sentences else 1.0
    findings.append(Finding("output", "research_citation_coverage", "block" if coverage < min_coverage else "pass",
                            f"{coverage:.0%} of sentences cite a source (minimum {min_coverage:.0%})"))
    m = find_promise(answer)
    findings.append(Finding("output", "research_no_promises", "block" if m else "pass",
                            f'promise-like wording: "{m.group(0)}"' if m else "no promises"))
    return findings


def _fact_percents(value: Any, out: set[float]) -> None:
    """Every number in the facts, as the percentages a writer could quote (one decimal)."""
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        for v in (value * 100, value):
            out.add(round(v, 1))
            out.add(round(v))
    elif isinstance(value, dict):
        for v in value.values():
            _fact_percents(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            _fact_percents(v, out)
    elif isinstance(value, str):
        for m in PERCENT.finditer(value):
            out.add(round(float(m.group(1)), 1))


def memo_text(memo: dict[str, Any]) -> str:
    return "\n".join([memo.get("headline", ""), memo.get("summary", ""), *memo.get("key_changes", []),
                      *memo.get("risks", [])])


def check_memo(memo: dict[str, Any], facts: dict[str, Any], valid_sources: set[int]) -> list[Finding]:
    text = memo_text(memo)
    # the writer's own sentences: quoted filing risks may legitimately mention guarantees or
    # other currencies (bank guarantees, export revenue in dollars)
    own = "\n".join([memo.get("headline", ""), memo.get("summary", ""), *memo.get("key_changes", [])])
    findings: list[Finding] = []

    m = find_promise(own)
    findings.append(Finding("output", "memo_no_promises", "block" if m else "pass",
                            f'promise-like wording: "{m.group(0)}"' if m else "no promises of returns"))

    allowed = set()
    _fact_percents(facts, allowed)
    quoted = [float(x) for x in PERCENT.findall(text)]
    # magnitudes: "trailed the index by 3.1%" quotes a fact of -0.031
    magnitudes = {abs(a) for a in allowed}
    ungrounded = sorted({q for q in quoted if not any(abs(abs(q) - a) <= 0.15 for a in magnitudes)})
    findings.append(Finding("output", "memo_numbers_grounded", "block" if ungrounded else "pass",
                            f"percentages not in the facts: {', '.join(f'{u}%' for u in ungrounded)}" if ungrounded
                            else f"all {len(quoted)} percentages match the facts"))

    market = facts.get("client", {}).get("market")
    # any stock the facts mention (plan, changes, research, exclusions) may be named
    known = {t for t in TICKER_TOKEN.findall(json.dumps(facts, default=str)) if t in BY_TICKER}
    named = {t for t in TICKER_TOKEN.findall(text) if t in BY_TICKER}
    foreign = sorted(t for t in named if t not in known
                     or (market and BY_TICKER[t].market != _market_code(market)))
    findings.append(Finding("output", "memo_tickers_known", "block" if foreign else "pass",
                            f"mentions stocks outside the plan or market: {', '.join(foreign)}" if foreign
                            else "every stock named is in the plan or the research"))

    cited = {int(n) for n in CITATION.findall(text)}
    bad = sorted(cited - valid_sources)
    findings.append(Finding("output", "memo_citations_exist", "block" if bad else "pass",
                            f"cites sources that do not exist: {bad}" if bad else "every [n] points to a retrieved source"))

    currency =facts.get("client", {}).get("currency")
    other = {"USD": "INR", "INR": "USD"}.get(currency)
    wrong = other and CURRENCY_MARKS[other].search(own)
    findings.append(Finding("output", "memo_currency", "block" if wrong else "pass",
                            f"uses {other} wording for a {currency} client" if wrong else f"amounts in {currency}"))

    has = bool(DISCLAIMER.search(text))
    findings.append(Finding("output", "memo_disclaimer", "pass" if has else "fixed",
                            "past-performance disclaimer present" if has else "disclaimer added"))
    return findings


def _market_code(name: str) -> str:
    return "IN" if "india" in name.lower() else "US"


def apply_fixes(memo: dict[str, Any], findings: list[Finding]) -> dict[str, Any]:
    if any(f.check == "memo_disclaimer" and f.verdict == "fixed" for f in findings):
        memo = {**memo, "summary": memo["summary"].rstrip() + " " + DISCLAIMER_TEXT}
    return memo


def feedback(findings: list[Finding]) -> str:
    """The critique given back to the writer for its second draft."""
    problems = [f"- {f.check}: {f.detail}" for f in findings if f.verdict == "block"]
    return ("Your previous draft failed these checks. Fix every one and use only the given facts:\n"
            + "\n".join(problems))
