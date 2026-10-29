
import pytest

from app.guardrails.citations import check_support, claims
from app.reliability import CircuitBreaker, backoff_delays, retry_async


def test_backoff_is_jittered_and_capped() -> None:
    delays = list(backoff_delays(6, base=0.5, cap=2.0))
    assert len(delays) == 5
    assert all(0 <= d <= 2.0 for d in delays)


@pytest.mark.anyio
async def test_retry_retries_transient_errors_only() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("slow")
        return "ok"

    assert await retry_async(flaky, attempts=3, base=0.001, retry_on=(TimeoutError,)) == "ok"
    assert calls["n"] == 3

    async def broken() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError):  # not retried: not a transient error
        await retry_async(broken, attempts=3, base=0.001, retry_on=(TimeoutError,))


def test_circuit_breaker_opens_and_recovers() -> None:
    now = [0.0]
    cb = CircuitBreaker("test", failure_threshold=2, reset_seconds=60, clock=lambda: now[0])
    assert cb.allow()
    cb.failure()
    assert cb.allow()
    cb.failure()
    assert not cb.allow() and cb.state == "open"
    now[0] += 59
    assert not cb.allow()  # still cooling down
    now[0] += 1
    assert cb.allow() and cb.state == "half_open"  # one trial call
    assert not cb.allow()  # ... and only one at a time
    cb.failure()
    assert not cb.allow()  # the trial failed: open again
    now[0] += 60
    cb.success()
    assert cb.state == "closed" and cb.allow()


def test_citation_gate() -> None:
    sources = {1: "Apple depends on suppliers in China and India for most of its products.",
               2: "The company faces intense competition in smartphones."}

    def score(query: str, passages: list[str]) -> list[float]:  # stand-in for the cross-encoder
        q = set(query.lower().split())
        return [len(q & set(p.lower().split())) / len(q) for p in passages]

    answer = ("Apple depends on suppliers in China and India [1]. "
              "Apple faces intense competition in smartphones [2]. "
              "Apple expects record profits from its car business [2].")
    assert [c[1] for c in claims(answer)] == [[1], [2], [2]]
    checks, finding = check_support(answer, sources, score, threshold=0.5)
    assert [c.supported for c in checks] == [True, True, False]
    assert finding.verdict == "warn"  # 1 of 3 unsupported
    _, finding = check_support("Apple sells cars [1]. Apple makes planes [2].", sources, score, threshold=0.5)
    assert finding.verdict == "block"


def test_citation_threshold_follows_the_reranker() -> None:
    from app.config import CITATION_THRESHOLDS, Settings

    for model, threshold in CITATION_THRESHOLDS.items():
        assert Settings(reranker_model=model).resolved_citation_threshold == threshold
    assert Settings(citation_support_threshold=1.5).resolved_citation_threshold == 1.5  # an explicit value wins
    with pytest.raises(ValueError, match="calibrate_citations"):
        _ = Settings(reranker_model="some/uncalibrated-model").resolved_citation_threshold
