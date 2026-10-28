"""Every score this project writes to Langfuse, with its meaning and range.

`ensure_score_configs()` registers them as Langfuse score configs, so the dashboard shows
the description next to each score and validates the value range. Names are grouped by
prefix: `rag_*` (retrieval and answer quality, mostly RAGAS), `output_*` (the final memo),
`portfolio_*`, `guardrail_*`, `memory_*` and `human_*`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreSpec:
    name: str
    data_type: str  # NUMERIC | BOOLEAN
    description: str
    min_value: float | None = 0.0
    max_value: float | None = 1.0


SCORES: tuple[ScoreSpec, ...] = (
    # RAG quality (RAGAS, LLM judge)
    ScoreSpec("rag_faithfulness", "NUMERIC",
              "RAGAS Faithfulness: share of the research answer's claims supported by the retrieved filings (LLM judge)."),
    ScoreSpec("rag_answer_relevancy", "NUMERIC",
              "RAGAS Answer Relevancy: how directly the research answer addresses the question (LLM judge + embeddings)."),
    ScoreSpec("rag_context_precision", "NUMERIC",
              "RAGAS Context Precision (no reference): whether the useful chunks are ranked first (LLM judge)."),
    ScoreSpec("rag_context_relevance", "NUMERIC",
              "RAGAS Context Relevance: how relevant the retrieved chunks are to the question (LLM judge)."),
    # RAG quality (deterministic, always available)
    ScoreSpec("rag_citation_coverage", "NUMERIC",
              "Share of answer sentences that cite a retrieved source [n]. Deterministic."),
    ScoreSpec("rag_numeric_grounding", "NUMERIC",
              "Share of numbers in the answer that appear in the retrieved sources. Deterministic."),
    ScoreSpec("rag_top_rerank_score", "NUMERIC",
              "Cross-encoder relevance of the best retrieved chunk (logit; higher is more relevant).",
              None, None),
    # Output quality
    ScoreSpec("output_memo_quality", "NUMERIC",
              "RAGAS rubric score (1-5, scaled to 0-1) of the final investment memo: accuracy, use of numbers, clarity, risk disclosure (LLM judge)."),
    ScoreSpec("output_rule_extraction_accuracy", "NUMERIC",
              "Share of mandate rules the compliance agent extracted correctly, checked against the hand-written truth file."),
    ScoreSpec("output_compliance_pass", "BOOLEAN",
              "1 if the final portfolio passed every mandate rule checked by the compliance agent.", None, None),
    # Portfolio
    ScoreSpec("portfolio_oos_sharpe", "NUMERIC",
              "Out-of-sample Sharpe ratio of the recommended portfolio (buy-and-hold after the estimation window).",
              None, None),
    ScoreSpec("portfolio_oos_excess_return_vs_benchmark", "NUMERIC",
              "Out-of-sample total return of the recommended portfolio minus the market index "
              "(S&P 500 for US clients, Nifty 50 for Indian clients) over the same days.", None, None),
    ScoreSpec("portfolio_baseline_gap", "NUMERIC",
              "Relative utility shortfall of the rule-of-thumb portfolio versus the best combination "
              "(what the exact search adds; 0 = same answer).", 0.0, None),
    # Guardrails and self-correction
    ScoreSpec("guardrail_input_blocked", "BOOLEAN",
              "1 if the input guardrails stopped the request (prompt injection or scope policy).", None, None),
    ScoreSpec("guardrail_pii_redacted", "NUMERIC",
              "Number of personal-data values removed from the request before storage, models and traces.",
              0.0, None),
    ScoreSpec("guardrail_quarantined_passages", "NUMERIC",
              "Retrieved passages kept out of the research prompt because they read like instructions "
              "(indirect prompt injection).", 0.0, None),
    ScoreSpec("guardrail_output_violations", "NUMERIC",
              "Output checks the memo's first draft failed (promises, ungrounded numbers, unknown stocks, "
              "bad citations, currency); each is fixed by a revision or the template.", 0.0, None),
    ScoreSpec("self_corrections", "NUMERIC",
              "Revisions the research and report agents made after failing a guardrail check.", 0.0, None),
    # Memory
    ScoreSpec("memory_items_recalled", "NUMERIC",
              "Long-term memory items recalled at intake (past reviews, preferences, advisor notes).", 0.0, None),
    ScoreSpec("research_cache_hit", "BOOLEAN",
              "1 if the research answer was reused from the semantic cache (same companies and index, "
              "near-identical question).", None, None),
    # Human in the loop
    ScoreSpec("human_approved", "BOOLEAN",
              "1 if the advisor approved the proposed trades, 0 if rejected.", None, None),
    ScoreSpec("human_revisions", "NUMERIC",
              "How many times the advisor pressed Change before deciding (fewer = better first proposals).",
              0.0, None),
    ScoreSpec("learned_preferences_applied", "NUMERIC",
              "Number of remembered advisor preferences applied to this run's first proposal.", 0.0, None),
)

BY_NAME = {s.name: s for s in SCORES}


def ensure_score_configs(client) -> dict[str, str]:  # noqa: ANN001 - langfuse.Langfuse
    """Create missing score configs; returns {name: config_id}. Safe to call repeatedly."""
    existing: dict[str, str] = {}
    page = 1
    while True:
        result = client.api.score_configs.get(page=page, limit=100)
        for cfg in result.data:
            if not getattr(cfg, "is_archived", False):
                existing.setdefault(cfg.name, cfg.id)
        if page >= (result.meta.total_pages or 1):
            break
        page += 1
    for spec in SCORES:
        if spec.name in existing:
            continue
        kwargs = {"name": spec.name, "data_type": spec.data_type, "description": spec.description}
        if spec.data_type == "NUMERIC":
            if spec.min_value is not None:
                kwargs["min_value"] = spec.min_value
            if spec.max_value is not None:
                kwargs["max_value"] = spec.max_value
        created = client.api.score_configs.create(**kwargs)
        existing[spec.name] = created.id
    return existing
