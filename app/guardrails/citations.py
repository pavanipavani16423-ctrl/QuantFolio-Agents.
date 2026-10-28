"""Citation gate: is each cited claim actually supported by the passage it cites?

The format checks (app.guardrails.output) catch citations to sources that do not exist. This
gate goes further: for every answer sentence with [n] markers, the cross-encoder reranker
scores (claim, cited passage). A claim is supported when the best score among its cited
passages reaches the calibrated threshold (scripts/calibrate_citations.py picks it from true
pairs and hard negatives - other passages of the same company). Unsupported claims fail the
gate; the research agent then revises once with the list of unsupported sentences, and falls
back to the extractive answer (which quotes its sources) if the revision still fails.
"""

import re
from dataclasses import dataclass

from app.guardrails import Finding

CITE = re.compile(r"\[(\d+)\]")


@dataclass
class ClaimCheck:
    sentence: str
    cited: list[int]
    score: float | None
    supported: bool


def claims(answer: str) -> list[tuple[str, list[int]]]:
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", answer.strip()):
        cited = [int(n) for n in CITE.findall(sentence)]
        text = CITE.sub("", sentence).strip()
        if cited and len(text) > 15:
            out.append((text, cited))
    return out


def check_support(answer: str, sources: dict[int, str], score_fn, threshold: float,  # noqa: ANN001
                  max_unsupported_share: float = 0.34) -> tuple[list[ClaimCheck], Finding]:
    """`score_fn(query, [passages]) -> [scores]` (the index's cross-encoder)."""
    checks: list[ClaimCheck] = []
    for text, cited in claims(answer):
        passages = [sources[n] for n in cited if n in sources]
        if not passages:
            checks.append(ClaimCheck(text, cited, None, False))
            continue
        best = max(score_fn(text, passages))
        checks.append(ClaimCheck(text, cited, round(float(best), 3), best >= threshold))
    if not checks:
        return checks, Finding("output", "citation_support", "pass", "no cited claims to verify")
    unsupported = [c for c in checks if not c.supported]
    share = len(unsupported) / len(checks)
    verdict = "block" if share > max_unsupported_share else ("warn" if unsupported else "pass")
    detail = (f"{len(checks) - len(unsupported)} of {len(checks)} cited claims are supported by their source"
              + (": unsupported - " + " | ".join(f'"{c.sentence[:90]}" [{",".join(map(str, c.cited))}]'
                                                for c in unsupported[:3]) if unsupported else ""))
    return checks, Finding("output", "citation_support", verdict, detail)
