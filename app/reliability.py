"""Reliability primitives shared by the LLM gateway, the A2A client and the MCP hub.

* `backoff_delays`  exponential backoff with full jitter (AWS Architecture Blog, "Exponential
                    Backoff And Jitter"): retries spread out instead of hammering a rate limit
                    in lock-step.
* `retry_async`     retries a coroutine on transient errors only, with those delays.
* `CircuitBreaker`  after N consecutive failures a dependency is skipped for a cool-down period
                    (closed -> open -> half-open -> closed), so a provider outage turns into fast,
                    honest fallbacks instead of every run waiting for timeouts.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def backoff_delays(attempts: int, base: float = 0.5, cap: float = 8.0) -> Iterator[float]:
    """Delays before retry 1..attempts-1: uniform(0, min(cap, base * 2**i))."""
    for i in range(max(0, attempts - 1)):
        yield random.uniform(0, min(cap, base * 2**i))


async def retry_async(fn: Callable[[], Awaitable[T]], *, attempts: int = 3, base: float = 0.5, cap: float = 8.0,
                      retry_on: tuple[type[BaseException], ...] = (Exception,), label: str = "call") -> T:
    delays = list(backoff_delays(attempts, base, cap))
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            if attempt == attempts - 1:
                raise
            delay = delays[attempt]
            logger.warning("%s failed (%s: %s); retry %d/%d in %.1f s", label, type(exc).__name__,
                           str(exc)[:120], attempt + 1, attempts - 1, delay)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 4, reset_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock  # injectable, so tests control time instead of sleeping
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: float | None = None
        self._trial = False  # a half-open trial call is in flight

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.reset_seconds else "open"

    def allow(self) -> bool:
        """False while open; in half-open exactly one trial call is let through."""
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._trial:
            self._trial = True
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self._trial = False

    def neutral(self) -> None:
        """The call ended without saying anything about the dependency (e.g. a malformed
        answer): release the trial slot without changing the state."""
        self._trial = False

    def failure(self) -> None:
        self.failures += 1
        was_trial, self._trial = self._trial, False
        if was_trial or self.failures >= self.failure_threshold:
            if self.opened_at is None or was_trial:
                logger.warning("circuit %s opened after %d failures", self.name, self.failures)
            self.opened_at = self.clock()

    def snapshot(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state, "failures": self.failures}


_BREAKERS: dict[str, CircuitBreaker] = {}


def breaker(name: str, failure_threshold: int = 4, reset_seconds: float = 60.0) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name, failure_threshold, reset_seconds)
    return _BREAKERS[name]


def breakers() -> list[dict[str, Any]]:
    return [b.snapshot() for b in _BREAKERS.values()]
