"""Guardrails: deterministic checks around every place text enters or leaves the agents.

    layer       where                                   checks
    input       the advisor's request                   PII redaction, prompt injection, scope policy
    retrieval   passages from the RAG index             indirect prompt injection (quarantine)
    memory      advisor notes before they are reused    prompt injection, PII
    output      research answer and memo                citations, promises, numbers, tickers,
                                                        currency, disclaimer (self-correction)
    action      orders at the broker                    approval token, order limits

Every check returns `Finding`s. They are stored on the run, shown in the UI ("Safety checks"),
written to Langfuse as guardrail observations, and summarized as scores. The checks are rules,
not model calls: they are fast, reproducible, and cannot be talked out of their decision.
"""

from dataclasses import asdict, dataclass

Verdict = str  # pass | warn | fixed | block


@dataclass
class Finding:
    layer: str
    check: str
    verdict: Verdict
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def worst(findings: list[Finding]) -> Verdict:
    order = {"pass": 0, "fixed": 1, "warn": 2, "block": 3}
    return max((f.verdict for f in findings), key=order.get, default="pass")
