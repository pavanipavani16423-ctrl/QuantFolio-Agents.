"""A2A plumbing shared by the remote agents and the orchestrator's client.

Message contract (JSON in a data part):

    request : {"skill": "<skill id>", "input": {...}}
              metadata: {"run_id", "trace_id", "parent_span_id"}   (W3C-style trace hand-off)
    response: {"skill": "...", "result": {...}, "tool_calls": [...], "llm_calls": [...]}

The trace ids in the metadata let the remote agent open its Langfuse span inside the caller's
trace, so one run is one trace even though it crosses service boundaries.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import get_data_parts, new_data_message, new_data_part, new_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Role,
    SendMessageRequest,
)
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict

from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

RPC_PATH = "/rpc"
AGENT_CARD_PATH = "/.well-known/agent-card.json"
SkillHandler = Callable[[dict[str, Any], "SkillContext"], Awaitable[dict[str, Any]]]


class SkillContext:
    """Per-request helpers for a skill: tool-call and LLM-call logs returned to the caller."""

    def __init__(self, run_id: str | None) -> None:
        self.run_id = run_id
        self.tool_calls: list[dict[str, Any]] = []
        self.llm_calls: list[dict[str, Any]] = []

    async def record_tool(self, info: dict[str, Any]) -> None:
        self.tool_calls.append(info)

    async def record_llm(self, info: dict[str, Any]) -> None:
        self.llm_calls.append(info)


class SkillExecutor(AgentExecutor):
    def __init__(self, agent_name: str, skills: dict[str, SkillHandler]) -> None:
        self.agent_name = agent_name
        self.skills = skills

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        parts = get_data_parts(context.message.parts) if context.message else []
        payload = parts[0] if parts else {}
        meta = MessageToDict(context.message.metadata) if context.message and context.message.metadata else {}
        skill = payload.get("skill")
        trace_context = None
        if meta.get("trace_id"):
            trace_context = {"trace_id": meta["trace_id"]}
            if meta.get("parent_span_id"):
                trace_context["parent_span_id"] = meta["parent_span_id"]
        ctx = SkillContext(meta.get("run_id"))
        tracer = get_tracer()
        with tracer.section(f"A2A {self.agent_name}: {skill}", as_type="agent",
                            input=payload.get("input"), trace_context=trace_context,
                            metadata={"service": self.agent_name, "protocol": "A2A 1.0",
                                      "run_id": ctx.run_id}) as span:
            if skill not in self.skills:
                body = {"skill": skill, "error": f"unknown skill {skill!r}; have {sorted(self.skills)}"}
                span.update(level="ERROR", status_message=body["error"])
            else:
                try:
                    result = await self.skills[skill](payload.get("input") or {}, ctx)
                    body = {"skill": skill, "result": result}
                    span.update(output=_short(result))
                except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised
                    logger.exception("A2A skill %s failed", skill)
                    body = {"skill": skill, "error": f"{type(exc).__name__}: {exc}"}
                    span.update(level="ERROR", status_message=body["error"])
        body["tool_calls"] = ctx.tool_calls
        body["llm_calls"] = ctx.llm_calls
        await event_queue.enqueue_event(new_data_message(body, role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None


def _short(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_short(v) if isinstance(v, (dict, list)) else v) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return value[:10]
    return value


def agent_card(name: str, description: str, base_url: str, skills: list[AgentSkill]) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        provider=AgentProvider(organization="QuantFolio Agents (demo)", url=base_url),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0",
                                             url=base_url.rstrip("/") + RPC_PATH)],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=skills,
    )


def add_agent_routes(app: FastAPI, card: AgentCard, executor: SkillExecutor, prefix: str) -> None:
    """Serve one agent under `prefix` (e.g. /a2a/risk): its Agent Card at
    <prefix>/.well-known/agent-card.json and JSON-RPC at <prefix>/rpc. The same paths are used
    whether the agent shares the API server or runs as its own service."""
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(),
                                    agent_card=card)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card, card_url=f"{prefix}{AGENT_CARD_PATH}"),
        jsonrpc_routes=create_jsonrpc_routes(handler, f"{prefix}{RPC_PATH}"),
    )


class A2AError(Exception):
    pass


class A2AAgentClient:
    """Calls one remote agent. `transport` lets tests (or the fallback) talk to an ASGI app."""

    def __init__(self, base_url: str, timeout: float = 120.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        self.card: dict[str, Any] | None = None

    async def ask(self, skill: str, data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout,
                                     base_url=self.base_url) as http:
            card_response = await http.get(f"{self.base_url}{AGENT_CARD_PATH}")
            card_response.raise_for_status()
            self.card = card_response.json()
            client = await create_client(self.base_url, client_config=ClientConfig(
                httpx_client=http, streaming=False))
            message = new_message(parts=[new_data_part({"skill": skill, "input": data})],
                                  role=Role.ROLE_USER)
            message.metadata.update({k: v for k, v in metadata.items() if v is not None})
            body = None
            async for response in client.send_message(SendMessageRequest(message=message)):
                if response.HasField("message"):
                    parts = get_data_parts(response.message.parts)
                    body = parts[0] if parts else None
                elif response.HasField("task") and response.task.history:
                    parts = get_data_parts(response.task.history[-1].parts)
                    body = parts[0] if parts else None
        if body is None:
            raise A2AError(f"{self.base_url}: empty response")
        if "error" in body:
            raise A2AError(f"{self.base_url} {skill}: {body['error']}")
        return body


async def ask_with_fallback(primary: A2AAgentClient, local_app: Any, skill: str,
                            data: dict[str, Any], metadata: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Network A2A first; if the service is unreachable, the same protocol against the
    ASGI app that hosts the agent in this process (no socket)."""
    try:
        return await primary.ask(skill, data, metadata), "http"
    except (TimeoutError, httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as exc:
        # unreachable, or something else answers on that port (no agent card there)
        if local_app is None or (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code != 404
        ):
            raise
        logger.warning("A2A %s unreachable (%s); using in-process transport", primary.base_url, exc)
        local = A2AAgentClient(primary.base_url, primary.timeout,
                               transport=httpx.ASGITransport(app=local_app))
        return await local.ask(skill, data, metadata), "in-process"
