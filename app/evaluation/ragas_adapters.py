"""Adapters that let RAGAS (0.4 metric collections) use this project's models.

* `TracedJudgeLLM` - any LangChain chat model (Groq by default) as the RAGAS judge; every
  judge call is a Langfuse generation, so evaluation cost and prompts are visible too.
* `FastEmbedEmbeddings` - the same local bge-small model the retriever uses.
"""

import asyncio
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
    def __init__(self, chat: Any, model_name: str, timeout: float = 90.0) -> None:
        self.chat = chat
        self.model_name = model_name
        self.timeout = timeout
        self.calls = 0
        self.tokens = 0

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        tracer = get_tracer()
        runnable = self.chat.with_structured_output(response_model, include_raw=True)
        last: Exception | None = None
        for attempt in (1, 2):
            with tracer.section(f"judge.{response_model.__name__}", as_type="generation",
                                model=self.model_name, input=prompt[:6000],
                                metadata={"role": "RAGAS judge", "attempt": attempt}) as gen:
                started = time.perf_counter()
                try:
                    out = await asyncio.wait_for(runnable.ainvoke([HumanMessage(content=prompt)]),
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
    try:
        chat = create_chat_model(settings, provider, settings.resolved_judge_model, max_tokens=4096)
    except LLMConfigError:
        return None
    return TracedJudgeLLM(chat, f"{provider}:{settings.resolved_judge_model}")


class FastEmbedEmbeddings(BaseRagasEmbedding):
    """Wraps `HybridIndex.embed_query` (which serializes access to the ONNX session)."""

    def __init__(self, index: Any) -> None:
        super().__init__()
        self.index = index

    def embed_text(self, text: str, **kwargs: Any) -> list[float]:
        return [float(x) for x in self.index.embed_query(text)]

    async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)
