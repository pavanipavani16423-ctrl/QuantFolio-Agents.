"""Per-run dependencies and the step helper every agent node uses.

`RunContext.step()` does three things for one agent step:
1. opens a numbered Langfuse section (the clear tree you see in the trace),
2. streams "running" / "done" / "failed" events to the UI (Server-Sent Events),
3. times the step.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.llm.gateway import LLMGateway
from app.mcp.hub import MCPHub
from app.observability.tracing import Tracer

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class StepSpec:
    number: int
    title: str
    as_type: str
    plain: str  # what the UI says, for non-experts


STEPS: dict[str, StepSpec] = {
    "intake": StepSpec(1, "Intake agent - understand the request", "agent",
                       "Reading your request"),
    "research": StepSpec(2, "Research agent - hybrid RAG over SEC filings", "agent",
                         "Reading company annual reports"),
    "risk": StepSpec(3, "Risk agent (A2A) - market risk profile", "agent",
                     "Measuring how risky each stock is"),
    "mandate": StepSpec(4, "Compliance agent (A2A) - read the client mandate", "agent",
                        "Reading the client's investment rules"),
    "optimize": StepSpec(5, "Portfolio optimizer - classical vs quantum vs hybrid", "agent",
                         "Choosing the best stocks: normal vs quantum computer"),
    "backtest": StepSpec(6, "Backtest - out-of-sample performance", "tool",
                         "Testing the portfolio on recent months it never saw"),
    "check": StepSpec(7, "Compliance and risk check (A2A)", "guardrail",
                      "Double-checking every rule"),
    "report": StepSpec(8, "Report writer - investment memo", "agent",
                       "Writing the recommendation"),
    "evaluate": StepSpec(9, "Quality evaluation - RAGAS and checks", "evaluator",
                         "Scoring the quality of the answer"),
    "trades": StepSpec(10, "Trade proposal - paper broker (MCP)", "tool",
                       "Preparing the buy and sell orders"),
    "approval": StepSpec(11, "Human approval", "span", "Waiting for the advisor to approve"),
    "execute": StepSpec(12, "Paper trade execution (MCP)", "tool", "Placing the practice trades"),
}


class StepHandle:
    def __init__(self, observation: Any) -> None:
        self.observation = observation
        self.summary: str | None = None
        self.output: Any = None
        self.metadata: dict[str, Any] = {}

    def done(self, summary: str, output: Any = None, **metadata: Any) -> None:
        self.summary = summary
        self.output = output
        self.metadata.update(metadata)


@dataclass
class RunContext:
    run_id: str
    settings: Settings
    tracer: Tracer
    llm: LLMGateway
    emit: Emit
    hub: MCPHub | None = None
    trace_id: str | None = None
    attempt_counter: dict[str, int] = field(default_factory=dict)

    @asynccontextmanager
    async def step(self, key: str, input: Any = None) -> AsyncIterator[StepHandle]:
        spec = STEPS[key]
        attempt = self.attempt_counter.get(key, 0) + 1
        self.attempt_counter[key] = attempt
        name = f"{spec.number:02d} {spec.title}" + (f" (attempt {attempt})" if attempt > 1 else "")
        await self.emit("step", {"key": key, "status": "running", "title": spec.plain,
                                 "attempt": attempt})
        started = time.perf_counter()
        with self.tracer.section(name, as_type=spec.as_type, input=input,
                                 metadata={"step": key, "attempt": attempt}) as obs:
            handle = StepHandle(obs)
            try:
                yield handle
            except Exception as exc:
                obs.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                await self.emit("step", {"key": key, "status": "failed", "title": spec.plain,
                                         "error": f"{type(exc).__name__}: {exc}"[:500],
                                         "seconds": round(time.perf_counter() - started, 2)})
                raise
            obs.update(output=handle.output if handle.output is not None else handle.summary,
                       metadata={"step": key, "attempt": attempt, **handle.metadata})
        await self.emit("step", {"key": key, "status": "done", "title": spec.plain,
                                 "summary": handle.summary, "attempt": attempt,
                                 "seconds": round(time.perf_counter() - started, 2)})

    def toolbox(self, agent: str):  # noqa: ANN201
        if self.hub is None:
            raise RuntimeError("MCP hub not connected")
        return self.hub.toolbox(agent)

    def a2a_metadata(self) -> dict[str, Any]:
        trace = self.tracer.trace_context() or {}
        return {"run_id": self.run_id, **trace}


_CONTEXTS: dict[str, RunContext] = {}


def register(ctx: RunContext) -> None:
    _CONTEXTS[ctx.run_id] = ctx


def unregister(run_id: str) -> None:
    _CONTEXTS.pop(run_id, None)


def get_context(run_id: str) -> RunContext:
    return _CONTEXTS[run_id]
