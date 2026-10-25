"""Adapters that let RAGAS (0.4 metric collections) use this project's models.

* `TracedJudgeLLM` - any LangChain chat model (Groq by default) as the RAGAS judge; every
  judge call is a Langfuse generation, so evaluation cost and prompts are visible too.
* `FastEmbedEmbeddings` - the same local bge-small model the retriever uses.
"""

import asyncio
import json
import time
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM

from app.config import Settings
from app.llm.providers import LLMConfigError, create_chat_model
from app.observability.tracing import get_tracer

T = TypeVar("T", bound=BaseModel)


class TracedJudgeLLM(InstructorBaseRagasLLM):
    """A pool of judge models used in turn (round robin). Free-tier rate limits are per model,
    so a pool multiplies throughput, and when one model fails a call (e.g. a malformed tool
    call) the next one retries it."""

    def __init__(self, chat: Any, model_name: str, timeout: float = 120.0,
                 pool: list[tuple[Any, str]] | None = None) -> None:
        self.pool = pool or [(chat, model_name)]
        self.model_name = " + ".join(name for _, name in self.pool)
        self.timeout = timeout
        self.calls = 0
        self.tokens = 0
        self._next = 0

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        tracer = get_tracer()
        last: Exception | None = None
        start = self._next
        self._next = (self._next + 1) % len(self.pool)
        order = [self.pool[(start + i) % len(self.pool)] for i in range(len(self.pool))]
        # first a tool call (structured output) on each model; if a provider rejects the tool
        # call (Groq "tool_use_failed" on long prompts), ask for plain JSON with the schema
        attempts = [(chat, name, "function_calling") for chat, name in order]
        attempts += [(chat, name, "json_mode") for chat, name in order]
        schema_hint = (
            "\n\nReturn ONLY a JSON object that matches this JSON schema, with no other text:\n"
            + json.dumps(response_model.model_json_schema())
        )
        for attempt, (chat, model_name, method) in enumerate(attempts, 1):
            runnable = chat.with_structured_output(response_model, include_raw=True, method=method)
            message = prompt + schema_hint if method == "json_mode" else prompt
            with tracer.section(f"judge.{response_model.__name__}", as_type="generation",
                                model=model_name, input=prompt[:6000],
                                metadata={"role": "RAGAS judge", "attempt": attempt,
                                          "method": method}) as gen:
                started = time.perf_counter()
                try:
                    out = await asyncio.wait_for(runnable.ainvoke([HumanMessage(content=message)]),
                                                 timeout=self.timeout)
                    parsed = out.get("parsed")
                    if parsed is None:
                        raise ValueError(f"judge returned no structured output: {out.get('parsing_error')}")
                    if isinstance(parsed, dict):
                        parsed = response_model.model_validate(parsed)
                    meta = getattr(out.get("raw"), "usage_metadata", None) or {}
                    usage = {"input": int(meta.get("input_tokens", 0)),
                             "output": int(meta.get("output_tokens", 0))}
                    self.calls += 1
                    self.tokens += usage["input"] + usage["output"]
                    gen.update(output=parsed.model_dump(mode="json"), usage_details=usage,
                               metadata={"latency_ms": round((time.perf_counter() - started) * 1000)})
                    return parsed
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    gen.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}"[:400])
        raise RuntimeError(f"judge failed: {last}")

    def generate(self, prompt: str, response_model: type[T]) -> T:
        return asyncio.run(self.agenerate(prompt, response_model))


def make_judge(settings: Settings) -> TracedJudgeLLM | None:
    provider = settings.resolved_judge_provider
    if provider == "mock" or not settings.provider_ready(provider):
        return None
    pool = []
    # JUDGE_MODEL may list several models separated by commas: they are used in turn
    for model in [m.strip() for m in settings.resolved_judge_model.split(",") if m.strip()]:
        try:
            # verdicts are short; a small cap keeps each request under per-minute output limits
            pool.append((create_chat_model(settings, provider, model, max_tokens=900),
                         f"{provider}:{model}"))
        except LLMConfigError:
            continue
    if not pool:
        return None
    return TracedJudgeLLM(None, "", pool=pool)


class FastEmbedEmbeddings(BaseRagasEmbedding):
    """Wraps `HybridIndex.embed_query` (which serializes access to the ONNX session)."""

    def __init__(self, index: Any) -> None:
        super().__init__()
        self.index = index

    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        return [float(x) for x in self.index.embed_query(text)]

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)
