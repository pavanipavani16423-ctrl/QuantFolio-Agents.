from pathlib import Path

import pytest
from pydantic import BaseModel

from app.evaluation.online import citation_coverage, numeric_grounding, rule_extraction_accuracy
from app.evaluation.ragas_adapters import TracedJudgeLLM

TRUTH = Path(__file__).resolve().parents[2] / "data" / "eval" / "mandate_truth.json"


def test_citation_coverage() -> None:
    assert citation_coverage("Apple sells phones [1]. It also sells services.") == 0.5
    assert citation_coverage("") is None


def test_numeric_grounding_ignores_citations() -> None:
    contexts = ["Revenue was $416.2 billion in fiscal 2025."]
    assert numeric_grounding("Revenue was $416.2 billion [3].", contexts) == 1.0
    assert numeric_grounding("Revenue was $500.0 billion [3].", contexts) == 0.0
    assert numeric_grounding("No numbers here [2].", contexts) is None


def test_rule_extraction_accuracy() -> None:
    good = {"holdings": 8, "max_weight": 0.2, "min_weight": 0.05, "max_sector_weight": 0.4,
            "max_volatility": 0.25, "risk_aversion": 3, "excluded_sectors": ["Energy"],
            "excluded_tickers": [], "approval_required": True}
    assert rule_extraction_accuracy("C-102", good, TRUTH) == 1.0
    assert rule_extraction_accuracy("C-102", {**good, "holdings": 9}, TRUTH) == pytest.approx(8 / 9)


class _StructuredFake:
    """A stand-in chat model: `with_structured_output` returns canned objects by schema name."""

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers

    def with_structured_output(self, schema: type[BaseModel], include_raw: bool = False):  # noqa: ANN201, FBT001
        answers = self.answers

        class _Runnable:
            async def ainvoke(self, _messages):  # noqa: ANN001, ANN202
                return {"parsed": schema.model_validate(answers[schema.__name__]), "raw": None}

        return _Runnable()


@pytest.mark.anyio
async def test_ragas_faithfulness_runs_through_the_traced_judge() -> None:
    """Plumbing test of the RAGAS 0.4 adapter (no network): statements -> NLI verdicts -> score."""
    from ragas.metrics.collections import Faithfulness

    judge = TracedJudgeLLM(_StructuredFake({
        "StatementGeneratorOutput": {"statements": ["Apple sells iPhones.", "Apple sells cars."]},
        "NLIStatementOutput": {"statements": [
            {"statement": "Apple sells iPhones.", "reason": "stated", "verdict": 1},
            {"statement": "Apple sells cars.", "reason": "not stated", "verdict": 0},
        ]},
    }), "fake:judge")
    result = await Faithfulness(llm=judge).ascore(
        user_input="What does Apple sell?", response="Apple sells iPhones and cars.",
        retrieved_contexts=["Apple designs and sells iPhones."])
    assert result.value == pytest.approx(0.5)
    assert judge.calls == 2
