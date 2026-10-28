"""Langfuse tracing with one trace per run and one clearly named section per step.

A run produces this tree in Langfuse (numbers keep the order readable):

    portfolio-run                                    (trace, tags: client, profile, llm)
    ├── 01 Input guardrails                          guardrail (PII, prompt injection, scope)
    ├── 02 Intake agent - recall memory              agent
    │   └── llm.intake                               generation (when an LLM is configured)
    ├── 03 Research agent - hybrid RAG               agent
    │   ├── rag.search "<query>"                     retriever (BM25 / dense / RRF / rerank)
    │   ├── llm.research_answer                      generation
    │   └── llm.research_answer_revision             generation (only after a failed check)
    ├── 04 Risk agent (A2A)                          agent  -> remote span from the A2A service
    ├── 05 Compliance agent (A2A) - mandate rules    agent  -> remote span from the A2A service
    ├── 06 Portfolio optimizer                       agent
    │   └── mcp.optimizer.select_stocks              tool
    ├── 07 Backtest (out-of-sample)                  tool
    ├── 08 Compliance check (A2A)                    guardrail
    ├── 09 Report writer - output guardrails         agent
    ├── 10 Quality evaluation (RAGAS)                evaluator  -> scores on the trace
    └── 11 Trades / 12 Human approval / 13 Execute   tool / span / tool (later, same trace)

Personal data is masked out of every input, output and metadata field before export.
When Langfuse keys are missing every call is a no-op, so the code path is identical.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class _NoopObservation:
    id = None
    trace_id = None

    def update(self, **_: Any) -> "_NoopObservation":
        return self

    def score(self, **_: Any) -> None:
        return None

    def score_trace(self, **_: Any) -> None:
        return None


NOOP = _NoopObservation()


def _mask(*, data: Any, **_: Any) -> Any:
    from app.guardrails.pii import redact_any

    try:
        return redact_any(data)
    except Exception:  # noqa: BLE001 - masking must never drop a trace
        return data


class Tracer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None
        self.score_config_ids: dict[str, str] = {}
        if settings.langfuse_enabled:
            try:
                from langfuse import Langfuse
                from langfuse.span_filter import is_langfuse_span

                self.client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    base_url=settings.langfuse_base_url,
                    environment=settings.langfuse_environment,
                    # only this project's spans: the MCP SDK also emits OpenTelemetry spans
                    # (gen_ai.* attributes) that would show up as loose top-level tools
                    should_export_span=is_langfuse_span,
                    # personal data never reaches the trace store (inputs, outputs, metadata)
                    mask=_mask if settings.guardrails_enabled else None,
                )
            except Exception as exc:  # noqa: BLE001 - tracing must never break a run
                logger.warning("langfuse disabled: %s", exc)
                self.client = None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def setup(self) -> None:
        """Register score configs once (needs network; failures only disable configs)."""
        if not self.enabled:
            return
        try:
            from app.observability.scores import ensure_score_configs

            self.score_config_ids = ensure_score_configs(self.client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse score configs not registered: %s", exc)

    # ---- traces and sections --------------------------------------------------------------
    @contextmanager
    def run_trace(self, *, name: str, run_id: str, input: Any, user_id: str | None,
                  session_id: str | None, tags: list[str], metadata: dict[str, Any],
                  trace_id: str | None = None) -> Iterator[Any]:
        if not self.enabled:
            yield NOOP
            return
        from langfuse import propagate_attributes

        trace_context = {"trace_id": trace_id} if trace_id else None
        with self.client.start_as_current_observation(
            name=name, as_type="chain", input=input, metadata=metadata,
            trace_context=trace_context,
        ) as root, propagate_attributes(
            trace_name=name, user_id=user_id, session_id=session_id, tags=tags,
            metadata={k: str(v) for k, v in metadata.items()},
        ):
            yield root

    @contextmanager
    def section(self, name: str, as_type: str = "span", input: Any = None,
                metadata: Any = None, trace_context: dict | None = None, **kwargs: Any) -> Iterator[Any]:
        if not self.enabled:
            yield NOOP
            return
        try:
            cm = self.client.start_as_current_observation(
                name=name, as_type=as_type, input=input, metadata=metadata,
                trace_context=trace_context, **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse section %s failed: %s", name, exc)
            cm = nullcontext(NOOP)
        with cm as obs:
            yield obs

    def current_trace_id(self) -> str | None:
        return self.client.get_current_trace_id() if self.enabled else None

    def current_observation_id(self) -> str | None:
        return self.client.get_current_observation_id() if self.enabled else None

    def trace_context(self) -> dict | None:
        """Context to hand to a remote agent so its spans join this trace."""
        trace_id = self.current_trace_id()
        if not trace_id:
            return None
        return {"trace_id": trace_id, "parent_span_id": self.current_observation_id()}

    def trace_url(self, trace_id: str | None) -> str | None:
        if not (self.enabled and trace_id):
            return None
        try:
            return self.client.get_trace_url(trace_id=trace_id)
        except Exception:  # noqa: BLE001
            return None

    # ---- scores ---------------------------------------------------------------------------
    def score(self, *, trace_id: str | None, name: str, value: float, comment: str | None = None,
              data_type: str | None = None, metadata: dict | None = None,
              observation_id: str | None = None) -> None:
        if not (self.enabled and trace_id) or value is None:
            return
        from app.observability.scores import BY_NAME

        spec = BY_NAME.get(name)
        data_type = data_type or (spec.data_type if spec else "NUMERIC")
        try:
            self.client.create_score(
                trace_id=trace_id, observation_id=observation_id, name=name,
                value=float(value), data_type=data_type, comment=comment,
                config_id=self.score_config_ids.get(name), metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse score %s failed: %s", name, exc)

    def flush(self) -> None:
        if self.enabled:
            try:
                self.client.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning("langfuse flush failed: %s", exc)


_TRACER: Tracer | None = None


def get_tracer() -> Tracer:
    global _TRACER
    if _TRACER is None:
        _TRACER = Tracer(get_settings())
    return _TRACER


def set_tracer(tracer: Tracer | None) -> None:
    """Tests replace the process tracer."""
    global _TRACER
    _TRACER = tracer
