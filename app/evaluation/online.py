"""Online evaluation of one run; every score is written to the run's Langfuse trace.

RAG quality (RAGAS 0.4, LLM judge - needs an LLM provider key):
    rag_faithfulness, rag_answer_relevancy, rag_context_precision, rag_context_relevance
Output quality:
    output_memo_quality (RAGAS rubric score, LLM judge), output_rule_extraction_accuracy,
    output_compliance_pass
Deterministic RAG checks (always):
    rag_citation_coverage, rag_numeric_grounding, rag_top_rerank_score
Portfolio / quantum:
    portfolio_oos_sharpe, portfolio_oos_excess_return_vs_spy, quantum_optimality_gap,
    quantum_feasible_probability, quantum_approximation_ratio

Without a judge the LLM metrics are reported as skipped (never invented).
"""

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any

from app.config import Settings
from app.evaluation.ragas_adapters import FastEmbedEmbeddings, make_judge

MEMO_RUBRIC = {
    "score1_description": "The memo is wrong or misleading: numbers contradict the facts, or it gives no clear recommendation.",
    "score2_description": "The memo has a recommendation but important numbers or risks are missing or wrong.",
    "score3_description": "The memo is mostly accurate but vague about risks, changes or how the methods compared.",
    "score4_description": "The memo is accurate and clear with minor omissions; risks and changes are stated.",
    "score5_description": "The memo is accurate, uses the given numbers correctly, states the main changes, cites risks, explains the quantum comparison honestly and avoids promises.",
}

CITATION = re.compile(r"\[(\d+)\]")
NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s) > 15]


def citation_coverage(answer: str) -> float | None:
    sentences = split_sentences(answer)
    if not sentences:
        return None
    return sum(bool(CITATION.search(s)) for s in sentences) / len(sentences)


def _norm_number(token: str) -> str:
    return token.replace("$", "").replace(",", "").rstrip(".")


def numeric_grounding(answer: str, contexts: list[str]) -> float | None:
    """Share of numbers in the answer that also appear in the sources (citations excluded)."""
    numbers = [_norm_number(n) for n in NUMBER.findall(CITATION.sub("", answer))]
    numbers = [n for n in numbers if len(n.rstrip("%")) > 1]
    if not numbers:
        return None
    haystack = {_norm_number(n) for n in NUMBER.findall(" ".join(contexts))}
    return sum(n in haystack for n in numbers) / len(numbers)


def rule_extraction_accuracy(client_id: str, rules: dict, truth_path: Path) -> float | None:
    if not truth_path.exists():
        return None
    truth = json.loads(truth_path.read_text()).get(client_id)
    if not truth:
        return None
    hits = 0
    for key, expected in truth.items():
        got = rules.get(key)
        if isinstance(expected, list):
            hits += sorted(got or []) == sorted(expected)
        elif isinstance(expected, bool):
            hits += bool(got) == expected
        else:
            hits += got is not None and math.isclose(float(got), float(expected), abs_tol=1e-6)
    return hits / len(truth)


async def _metric(name: str, coro, timeout: float = 180.0) -> tuple[str, float | None, str | None]:  # noqa: ANN001
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        value = float(result.value)
        if math.isnan(value):
            return name, None, "judge produced no statements to score"
        return name, value, getattr(result, "reason", None)
    except Exception as exc:  # noqa: BLE001
        return name, None, f"{type(exc).__name__}: {exc}"[:300]


async def ragas_scores(settings: Settings, question: str, answer: str, contexts: list[str],
                       memo_text: str, memo_facts: str) -> tuple[dict[str, dict], str | None, list[str]]:
    judge = make_judge(settings)
    if judge is None:
        return {}, None, ["RAGAS LLM metrics skipped: no judge model configured (set GROQ_API_KEY)"]
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
        ContextRelevance,
        Faithfulness,
        RubricsScoreWithoutReference,
    )

    from app.rag.index import get_index

    embeddings = FastEmbedEmbeddings(await asyncio.to_thread(get_index))
    jobs = [
        _metric("rag_faithfulness", Faithfulness(llm=judge).ascore(
            user_input=question, response=answer, retrieved_contexts=contexts)),
        _metric("rag_answer_relevancy", AnswerRelevancy(llm=judge, embeddings=embeddings).ascore(
            user_input=question, response=answer)),
        _metric("rag_context_precision", ContextPrecisionWithoutReference(llm=judge).ascore(
            user_input=question, response=answer, retrieved_contexts=contexts)),
        _metric("rag_context_relevance", ContextRelevance(llm=judge).ascore(
            user_input=question, retrieved_contexts=contexts)),
        _metric("output_memo_quality", RubricsScoreWithoutReference(llm=judge, rubrics=MEMO_RUBRIC).ascore(
            user_input="Write an investment memo for the advisor from these facts:\n" + memo_facts[:6000],
            response=memo_text)),
    ]
    scores: dict[str, dict] = {}
    notes: list[str] = []
    # sequential keeps a free-tier rate limit happy; each metric is still a few judge calls
    for job in jobs:
        name, value, reason = await job
        if value is None:
            notes.append(f"{name} not scored: {reason}")
            continue
        if name == "output_memo_quality":  # rubric 1-5 -> 0-1
            value = (value - 1) / 4
        scores[name] = {"value": value, "comment": reason, "source": "ragas"}
    return scores, judge.model_name, notes


async def evaluate_run(settings: Settings, state: dict[str, Any]) -> dict[str, Any]:
    research = state["research"]
    contexts = [s["text"] for s in research["sources"]]
    memo = state["memo"]
    memo_text = "\n".join([memo["headline"], memo["summary"], *memo["key_changes"], *memo["risks"],
                           memo["quantum_note"]])
    scores: dict[str, dict] = {}

    def put(name: str, value: float | None, comment: str, source: str = "deterministic") -> None:
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            scores[name] = {"value": float(value), "comment": comment, "source": source}

    put("rag_citation_coverage", citation_coverage(research["answer"]),
        "share of answer sentences with a [n] citation")
    put("rag_numeric_grounding", numeric_grounding(research["answer"], contexts),
        "share of numbers in the answer found in the sources")
    reranks = [s["rerank_score"] for s in research["sources"] if s.get("rerank_score") is not None]
    put("rag_top_rerank_score", max(reranks) if reranks else None, "best cross-encoder score")
    put("output_rule_extraction_accuracy",
        rule_extraction_accuracy(state["client_id"], state["rules"],
                                 Path(settings.data_dir) / "eval" / "mandate_truth.json"),
        "extracted mandate rules vs hand-written truth")
    put("output_compliance_pass", 1.0 if state["compliance"]["passed"] else 0.0,
        "all mandate rules pass" if state["compliance"]["passed"] else "a mandate rule failed")

    bt = state["backtest"]["metrics"]
    rec = bt.get("recommended", {})
    put("portfolio_oos_sharpe", rec.get("sharpe_ratio"), "out-of-sample Sharpe, buy-and-hold")
    if rec and "SPY" in bt:
        put("portfolio_oos_excess_return_vs_spy", rec["total_return"] - bt["SPY"]["total_return"],
            "out-of-sample total return minus SPY")
    opt = state["optimization"]
    if "quantum" in opt:
        put("quantum_optimality_gap", opt.get("quantum_gap"), "QAOA vs exact classical selection")
        put("quantum_feasible_probability", opt["quantum"].get("feasible_probability"),
            "probability mass on exactly-k selections")
        put("quantum_approximation_ratio", opt["quantum"].get("feasible_approximation_ratio"),
            "QAOA approximation ratio over feasible selections")

    notes: list[str] = []
    judge_name = None
    if settings.online_evaluation:
        llm_scores, judge_name, notes = await ragas_scores(
            settings, research["question"], research["answer"], contexts, memo_text,
            json.dumps(state.get("memo_facts", {}), default=str))
        scores.update(llm_scores)
    return {"scores": scores, "judge": judge_name, "notes": notes}
