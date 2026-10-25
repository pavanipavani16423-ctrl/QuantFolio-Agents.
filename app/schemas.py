"""Shared data models (agents, MCP tools, A2A messages, API)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Method = Literal["classical", "quantum", "hybrid"]


# ---- intake --------------------------------------------------------------------------------
class IntakeResult(BaseModel):
    """What the user wants, extracted from their request."""

    client_id: str = Field(description="Client id such as C-101, C-102 or C-103")
    wants_rebalance: bool = Field(True, description="True if the user asks for a new portfolio")
    research_question: str = Field(
        description="One clear question for the research analyst, answerable from 10-K filings"
    )
    focus_tickers: list[str] = Field(default_factory=list,
                                     description="Tickers the user mentions explicitly")


# ---- research (hybrid RAG) ----------------------------------------------------------------
class Source(BaseModel):
    n: int
    chunk_id: str
    doc_id: str
    doc_type: str
    ticker: str | None = None
    title: str
    section: str = ""
    source_url: str | None = None
    text: str
    rerank_score: float | None = None
    bm25_rank: int | None = None
    dense_rank: int | None = None


class RiskFlag(BaseModel):
    ticker: str
    risk: str = Field(description="One-sentence risk, taken from the sources")
    source: int = Field(description="Number n of the supporting source [n]")


class ResearchAnswer(BaseModel):
    """LLM output schema for the research analyst."""

    answer: str = Field(description="3-6 sentences. Cite every factual sentence with [n].")
    risk_flags: list[RiskFlag] = Field(default_factory=list)


class ResearchResult(BaseModel):
    question: str
    answer: str
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    sources: list[Source]
    queries: list[str]
    method: str  # llm | rules | rules_after_llm_error
    retrieval_mode: str


# ---- compliance ----------------------------------------------------------------------------
class RuleCitation(BaseModel):
    rule: str
    chunk_id: str
    quote: str


class MandateRules(BaseModel):
    """Machine-checkable rules extracted from a client's investment policy statement."""

    client_id: str
    holdings: int = Field(description="Exact number of stocks to hold")
    max_weight: float = Field(description="Maximum weight of one stock, as a fraction (0.15 = 15%)")
    min_weight: float = Field(description="Minimum weight of one held stock, as a fraction")
    max_sector_weight: float = Field(description="Maximum weight of one sector, as a fraction")
    max_volatility: float = Field(description="Maximum expected annualized volatility, fraction")
    risk_aversion: float = Field(description="Risk aversion coefficient for the optimizer")
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)
    approval_required: bool = True
    citations: list[RuleCitation] = Field(default_factory=list)


class RuleCheck(BaseModel):
    rule: str
    passed: bool
    detail: str
    citation: str | None = None


class ComplianceReport(BaseModel):
    passed: bool
    checks: list[RuleCheck]


# ---- portfolio -----------------------------------------------------------------------------
class Proposal(BaseModel):
    method: str
    label: str
    selected: list[str]
    weights: dict[str, float]
    expected_return: float
    volatility: float
    utility: float
    selection_utility: float
    seconds: float
    feasible: bool
    volatility_limit_met: bool
    details: dict[str, Any] = Field(default_factory=dict)


class Trade(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    shares: int
    price: float
    value: float
    weight_before: float
    weight_after: float


class Memo(BaseModel):
    """LLM output schema for the report writer."""

    headline: str = Field(description="One sentence: what we recommend and why")
    summary: str = Field(description="4-6 plain-language sentences for the client")
    key_changes: list[str] = Field(description="Bullet points: the main buys and sells")
    risks: list[str] = Field(description="Bullet points: the main risks, with source [n] when from filings")
    quantum_note: str = Field(description="1-2 sentences on how the quantum optimizer compared")


# ---- runs ----------------------------------------------------------------------------------
RunStatus = Literal["queued", "running", "awaiting_approval", "approved", "rejected",
                    "completed", "failed"]


class RunRequest(BaseModel):
    client_id: str = "C-102"
    request: str = Field(min_length=3, max_length=2000)
    methods: list[Method] = Field(default_factory=lambda: ["classical", "quantum", "hybrid"])


class StepInfo(BaseModel):
    key: str
    title: str
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"
    summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    seconds: float | None = None


class ChangeRequest(BaseModel):
    """What the advisor wants different. Applied at once (re-plan) and, if remembered, to every
    later run for the same client."""

    remove_tickers: list[str] = Field(default_factory=list, max_length=10)
    max_weight: float | None = Field(default=None, ge=0.03, le=0.5)
    lower_risk: bool = False


class ApprovalRequest(BaseModel):
    action: Literal["approve", "reject", "change"] | None = None
    approved: bool | None = None  # older clients send only this
    reviewer: str = Field(default="advisor", max_length=80)
    note: str | None = Field(default=None, max_length=500)
    changes: ChangeRequest | None = None
    remember: bool = True

    def resolved_action(self) -> str:
        if self.action:
            return self.action
        return "approve" if self.approved else "reject"
