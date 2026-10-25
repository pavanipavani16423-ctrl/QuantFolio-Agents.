"""Every score this project writes to Langfuse, with its meaning and range.

`ensure_score_configs()` registers them as Langfuse score configs, so the dashboard shows
the description next to each score and validates the value range. Names are grouped by
prefix: `rag_*` (retrieval and answer quality, mostly RAGAS), `output_*` (the final memo),
`portfolio_*`, `quantum_*` and `human_*`.
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
    # Portfolio and quantum
    ScoreSpec("portfolio_oos_sharpe", "NUMERIC",
              "Out-of-sample Sharpe ratio of the recommended portfolio (buy-and-hold after the estimation window).",
              None, None),
    ScoreSpec("portfolio_oos_excess_return_vs_spy", "NUMERIC",
              "Out-of-sample total return of the recommended portfolio minus SPY over the same days.", None, None),
    ScoreSpec("quantum_optimality_gap", "NUMERIC",
              "Relative utility gap of the QAOA selection to the proven classical optimum (0 = optimal)."),
    ScoreSpec("quantum_feasible_probability", "NUMERIC",
              "Probability mass of the final QAOA state on feasible selections (exactly k stocks)."),
    ScoreSpec("quantum_approximation_ratio", "NUMERIC",
              "QAOA approximation ratio over feasible selections (1 = all probability on the optimum)."),
    # Human in the loop
    ScoreSpec("human_approved", "BOOLEAN",
              "1 if the advisor approved the proposed trades, 0 if rejected.", None, None),
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
