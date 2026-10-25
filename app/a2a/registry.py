"""The remote agents, where they live, and how to call them."""

from typing import Any

from fastapi import FastAPI

from app.a2a import compliance_agent, risk_agent
from app.a2a.common import A2AAgentClient, add_agent_routes, ask_with_fallback
from app.config import Settings

AGENTS = {"risk": risk_agent, "compliance": compliance_agent}

# The ASGI app hosting the agents in this process (set by the API at startup); used when the
# configured URL is unreachable, e.g. the API runs on a different port than PUBLIC_BASE_URL.
_LOCAL_APP: Any = None


def agent_url(settings: Settings, name: str) -> str:
    configured = {"risk": settings.a2a_risk_url, "compliance": settings.a2a_compliance_url}[name]
    return (configured or f"{settings.public_base_url.rstrip('/')}/a2a/{name}").rstrip("/")


def mount_agents(app: FastAPI, settings: Settings, names: list[str] | None = None) -> None:
    global _LOCAL_APP
    for name in names or list(AGENTS):
        module = AGENTS[name]
        base = f"{settings.public_base_url.rstrip('/')}/a2a/{name}"
        add_agent_routes(app, module.card(base), module.executor(), f"/a2a/{name}")
    _LOCAL_APP = app


def set_local_app(app: Any) -> None:
    global _LOCAL_APP
    _LOCAL_APP = app


async def ask(settings: Settings, name: str, skill: str, data: dict[str, Any],
              metadata: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (response body, call info: url, transport, agent card name)."""
    client = A2AAgentClient(agent_url(settings, name), settings.a2a_timeout_seconds)
    body, transport = await ask_with_fallback(client, _LOCAL_APP, skill, data, metadata)
    info = {"agent": name, "url": client.base_url, "transport": transport, "skill": skill,
            "card": (client.card or {}).get("name")}
    return body, info
