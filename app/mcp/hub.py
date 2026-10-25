"""MCP client hub: one session per server for the lifetime of a run.

Transports
----------
* ``inprocess``: each server runs in this process behind `InMemoryTransport` - a full MCP
  JSON-RPC session (initialize, tools/list, tools/call) over memory streams.
* ``stdio``: each server is launched as ``python -m app.mcp.servers.<name>``.

Agents never see the hub; each gets a `Toolbox` limited by `AGENT_TOOL_ACL` (least privilege).
Every call becomes a Langfuse *tool* observation and an entry in the run's tool log.
"""

import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from mcp import Client
from mcp.client._memory import InMemoryTransport
from mcp.client.stdio import StdioServerParameters
from pydantic import BaseModel

from app.mcp.servers import broker, market_data, optimizer, research
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

SERVERS: dict[str, ModuleType] = {
    "market": market_data,
    "research": research,
    "optimizer": optimizer,
    "broker": broker,
}

# Which agent may call which tool ("server.tool" or "server.*").
AGENT_TOOL_ACL: dict[str, frozenset[str]] = {
    "research_agent": frozenset({"research.search_documents", "research.get_chunk"}),
    "risk_agent": frozenset({"market.*"}),
    "compliance_agent": frozenset({"research.search_documents", "market.get_portfolio_risk"}),
    "optimizer_agent": frozenset({"optimizer.*", "market.get_market_stats", "market.list_universe"}),
    "trader_agent": frozenset({"broker.*"}),
    "supervisor": frozenset({"broker.get_account", "market.list_universe"}),
    "evaluator": frozenset({"research.search_documents"}),
}

ToolRecorder = Callable[[dict[str, Any]], Awaitable[None]]


class MCPToolError(Exception):
    """The tool ran and reported a failure (bad arguments, infeasible request, ...)."""


class MCPTransportError(Exception):
    """The server could not be reached or did not answer in time."""


class MCPPermissionError(Exception):
    """The calling agent is not allowed to use this tool."""


def is_allowed(agent: str, server: str, tool: str) -> bool:
    allowed = AGENT_TOOL_ACL.get(agent, frozenset())
    return f"{server}.{tool}" in allowed or f"{server}.*" in allowed


def _preview(value: Any, depth: int = 0) -> Any:
    """Small summary of arguments/results for the trace and the UI."""
    if isinstance(value, dict):
        if depth >= 2:
            return f"<object: {len(value)} keys>"
        return {k: _preview(v, depth + 1) for k, v in list(value.items())[:14]}
    if isinstance(value, list):
        if len(value) <= 6 and all(isinstance(v, (str, int, float, bool)) for v in value):
            return value
        return f"<list: {len(value)} items>"
    if isinstance(value, str) and len(value) > 200:
        return value[:197] + "..."
    if isinstance(value, float):
        return round(value, 6)
    return value


def _jsonable(arguments: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in arguments.items():
        if value is None:
            continue
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        out[key] = value
    return out


class MCPHub:
    def __init__(self, transport: str = "inprocess", timeout: float = 300.0,
                 max_retries: int = 1, recorder: ToolRecorder | None = None) -> None:
        self.transport = transport
        self.timeout = timeout
        self.max_retries = max_retries
        self.recorder = recorder
        self._clients: dict[str, Client] = {}
        self._tools: dict[str, dict[str, Any]] = {}
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "MCPHub":
        self._stack = AsyncExitStack()
        try:
            for name, module in SERVERS.items():
                client = await self._stack.enter_async_context(
                    Client(self._target(module), read_timeout_seconds=self.timeout)
                )
                listing = await client.list_tools()
                self._clients[name] = client
                self._tools[name] = {tool.name: tool for tool in listing.tools}
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    def _target(self, module: ModuleType):  # noqa: ANN202
        if self.transport == "inprocess":
            return InMemoryTransport(module.build_server())
        if self.transport == "stdio":
            return StdioServerParameters(
                command=sys.executable, args=["-m", module.__name__],
                env={**os.environ, "PYTHONPATH": str(ROOT)}, cwd=str(ROOT),
            )
        raise ValueError(f"unknown MCP transport {self.transport!r}")

    def catalog(self) -> dict[str, list[dict[str, Any]]]:
        return {
            server: [{"name": t.name, "description": t.description} for t in tools.values()]
            for server, tools in self._tools.items()
        }

    def toolbox(self, agent: str) -> "Toolbox":
        return Toolbox(self, agent)

    async def _record(self, info: dict[str, Any]) -> None:
        level = logging.INFO if info["status"] == "ok" else logging.WARNING
        logger.log(level, "tool call %s.%s %s", info["server"], info["tool"], info["status"])
        if self.recorder is not None:
            await self.recorder(info)

    async def call(self, agent: str, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server not in self._clients:
            raise MCPToolError(f"unknown MCP server {server!r}")
        if tool not in self._tools[server]:
            raise MCPToolError(f"server {server!r} has no tool {tool!r}")
        payload = _jsonable(arguments)
        tracer = get_tracer()
        with tracer.section(f"mcp.{server}.{tool}", as_type="tool", input=_preview(payload),
                            metadata={"agent": agent, "transport": self.transport}) as obs:
            for attempt in range(1, self.max_retries + 2):
                started_at, started = datetime.now(UTC), time.perf_counter()
                base = {"agent": agent, "server": server, "tool": tool, "attempt": attempt,
                        "started_at": started_at.isoformat(), "args": _preview(payload)}
                try:
                    result = await self._clients[server].call_tool(
                        tool, payload, read_timeout_seconds=self.timeout)
                except Exception as exc:  # noqa: BLE001 - transport failure of any kind
                    message = f"{type(exc).__name__}: {exc}"
                    await self._record({**base, "status": "transport_error", "error": message,
                                        "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
                    if attempt <= self.max_retries:
                        continue
                    obs.update(level="ERROR", status_message=message)
                    raise MCPTransportError(f"{server}.{tool}: {message}") from exc
                latency = round((time.perf_counter() - started) * 1000, 1)
                if result.is_error:
                    message = " ".join(getattr(c, "text", "") for c in result.content).strip() or "tool error"
                    await self._record({**base, "status": "tool_error", "error": message, "latency_ms": latency})
                    obs.update(level="ERROR", status_message=message)
                    raise MCPToolError(f"{server}.{tool}: {message}")
                data = result.structured_content or {}
                await self._record({**base, "status": "ok", "latency_ms": latency,
                                    "result": _preview(data)})
                obs.update(output=_preview(data), metadata={"agent": agent, "latency_ms": latency,
                                                            "attempt": attempt})
                return data
        raise AssertionError("unreachable")


class Toolbox:
    """The MCP surface one agent can see and use."""

    def __init__(self, hub: MCPHub, agent: str) -> None:
        self.hub = hub
        self.agent = agent

    async def call(self, server: str, tool: str, **arguments: Any) -> dict[str, Any]:
        if not is_allowed(self.agent, server, tool):
            await self.hub._record({"agent": self.agent, "server": server, "tool": tool,
                                    "status": "denied", "error": "permission denied",
                                    "started_at": datetime.now(UTC).isoformat(), "latency_ms": 0})
            raise MCPPermissionError(f"{self.agent} may not call {server}.{tool}")
        return await self.hub.call(self.agent, server, tool, arguments)
