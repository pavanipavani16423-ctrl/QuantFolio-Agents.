"""Single entry point for every LLM call the agents make.

* `structured()` returns a validated Pydantic object (`with_structured_output`).
* Every call is a Langfuse *generation* (model, prompt, output, token usage, latency) inside
  the calling agent's section, and is also reported to the run log.
* Failures are retried once; after that the agent's deterministic fallback is used and the
  run records a warning. Nothing fails silently.
* With LLM_PROVIDER=mock no model is called: the fallback runs, and the run log says so, so
  every answer is truthful about what produced it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.config import Settings
from app.llm.providers import LLMConfigError, create_chat_model
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
CallRecorder = Callable[[dict[str, Any]], Awaitable[None]]


class LLMGateway:
    def __init__(self, settings: Settings, recorder: CallRecorder | None = None,
                 chat_model: Any | None = None) -> None:
        self.settings = settings
        self.provider = settings.llm_provider
        self.model_name = settings.resolved_llm_model
        self.recorder = recorder
        self.config_error: str | None = None
        self._chat = chat_model
        if self._chat is None and self.provider != "mock":
            try:
                self._chat = create_chat_model(settings, self.provider, self.model_name)
            except LLMConfigError as exc:
                self.config_error = str(exc)

    @property
    def available(self) -> bool:
        return self._chat is not None

    @property
    def mode(self) -> str:
        return f"{self.provider}:{self.model_name}" if self.available else "rule-based (no LLM)"

    async def _record(self, **info: Any) -> None:
        if self.recorder is not None:
            await self.recorder(info)

    async def structured(self, agent: str, schema: type[T], system: str, user: str,
                         fallback: Callable[[], T], attempts: int = 2) -> tuple[T, str]:
        """Returns (result, method) with method in {"llm", "rules", "rules_after_llm_error"}."""
        if not self.available:
            await self._record(agent=agent, status="skipped_no_llm", provider=self.provider,
                               error=self.config_error)
            return fallback(), "rules"

        tracer = get_tracer()
        runnable = self._chat.with_structured_output(schema, include_raw=True)
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        last_error = "unknown error"
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            with tracer.section(
                f"llm.{agent}", as_type="generation", model=self.model_name,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                metadata={"provider": self.provider, "attempt": attempt, "schema": schema.__name__},
                model_parameters={"temperature": self.settings.llm_temperature},
            ) as gen:
                try:
                    out = await asyncio.wait_for(runnable.ainvoke(messages),
                                                 timeout=self.settings.llm_timeout_seconds)
                    if out.get("parsing_error"):
                        raise ValueError(f"unparseable output: {out['parsing_error']}")
                    parsed = out.get("parsed")
                    if parsed is None:
                        raise ValueError("model returned no structured output")
                    if isinstance(parsed, dict):
                        parsed = schema.model_validate(parsed)
                    usage = _usage(out.get("raw"))
                    gen.update(output=parsed.model_dump(mode="json"), usage_details=usage or None)
                    await self._record(agent=agent, status="ok", provider=self.provider,
                                       model=self.model_name, attempt=attempt,
                                       latency_ms=round((time.perf_counter() - started) * 1000, 1),
                                       **usage)
                    return parsed, "llm"
                except Exception as exc:  # noqa: BLE001 - provider, timeout or validation error
                    last_error = f"{type(exc).__name__}: {exc}"[:500]
                    gen.update(level="ERROR", status_message=last_error)
                    await self._record(agent=agent, status="error", provider=self.provider,
                                       model=self.model_name, attempt=attempt, error=last_error,
                                       latency_ms=round((time.perf_counter() - started) * 1000, 1))
        logger.warning("%s: LLM failed after %d attempts (%s); using rules", agent, attempts, last_error)
        return fallback(), "rules_after_llm_error"


def _usage(message: Any) -> dict[str, int]:
    meta = getattr(message, "usage_metadata", None) or {}
    out = {}
    if "input_tokens" in meta:
        out["input"] = int(meta["input_tokens"])
    if "output_tokens" in meta:
        out["output"] = int(meta["output_tokens"])
    if out:
        out["total"] = out.get("input", 0) + out.get("output", 0)
    return out
