"""HTTP routes. Everything under /api/v1 needs X-API-Key (or ?api_key=) when API_KEY is set."""

import asyncio
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.a2a import registry
from app.config import ROOT
from app.data import store
from app.data.universe import BY_TICKER, MARKETS
from app.data.universe import universe as market_universe
from app.mcp.hub import AGENT_TOOL_ACL, MCPHub
from app.mcp.servers import broker
from app.observability.scores import SCORES
from app.observability.tracing import get_tracer
from app.schemas import ApprovalRequest, RunRequest
from app.services.runs import ConflictError

TERMINAL = {"completed", "failed", "rejected", "approved", "executed", "blocked"}


def require_key(request: Request) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    given = request.headers.get("x-api-key") or request.query_params.get("api_key") or ""
    if not hmac.compare_digest(given, expected.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


public = APIRouter()
api = APIRouter(dependencies=[Depends(require_key)])


@public.get("/health")
async def health(request: Request) -> dict[str, Any]:
    s = request.app.state.settings
    from app.evaluation.ragas_adapters import make_judge
    from app.llm.gateway import LLMGateway

    tracer = get_tracer()
    judge = make_judge(s)
    return {
        "status": "ok",
        "llm": LLMGateway(s).mode,
        "judge": judge.model_name if judge else None,
        "langfuse": {"enabled": tracer.enabled, "host": s.langfuse_base_url if tracer.enabled else None},
        "rag_index_ready": request.app.state.index_ready,
        "runs": await request.app.state.db.count_runs(),
        "a2a_agents": {name: registry.agent_url(s, name) for name in registry.AGENTS},
    }


# ---- clients ---------------------------------------------------------------------------------
@api.get("/clients")
async def clients() -> list[dict[str, Any]]:
    out = []
    for cid, acc in store.accounts().items():
        snap = await broker.get_account(cid)
        market = MARKETS[acc["market"]]
        out.append({"client_id": cid, "name": acc["name"], "profile": acc["profile"],
                    "mandate_doc": acc["mandate_doc"], "market_value": snap["market_value"],
                    "holdings": len(snap["positions"]), "price_date": snap["price_date"],
                    "market": market.code, "market_name": market.name, "currency": market.currency,
                    "currency_symbol": market.symbol, "benchmark_name": market.benchmark_name,
                    "research_sources": market.research_sources})
    return out


@api.get("/clients/{client_id}/preferences")
async def client_preferences(client_id: str, request: Request) -> list[dict[str, Any]]:
    """What the agents learned about this client from past reviews."""
    if client_id not in store.accounts():
        raise HTTPException(status_code=404, detail=f"unknown client {client_id}")
    return await request.app.state.db.preferences(client_id)


@api.delete("/clients/{client_id}/preferences/{pref_id}")
async def forget_preference(client_id: str, pref_id: int, request: Request) -> dict[str, Any]:
    if not await request.app.state.db.forget_preference(client_id, pref_id):
        raise HTTPException(status_code=404, detail="preference not found")
    return {"forgotten": pref_id}


@api.get("/clients/{client_id}/account")
async def client_account(client_id: str) -> dict[str, Any]:
    try:
        snap = await broker.get_account(client_id)
    except Exception as exc:  # noqa: BLE001 - unknown client
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snap["sectors"] = {t: BY_TICKER[t].sector for t in snap["positions"]}
    return snap


@api.post("/clients/{client_id}/reset")
async def reset_client(client_id: str) -> dict[str, Any]:
    try:
        broker.reset_account(client_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await broker.get_account(client_id)


@api.get("/universe")
async def universe(market: str = "US") -> dict[str, Any]:
    if market not in MARKETS:
        raise HTTPException(status_code=404, detail=f"unknown market {market}")
    return {"market": market,
            "assets": [{"ticker": a.ticker, "name": a.name, "sector": a.sector} for a in market_universe(market)],
            "prices": store.prices_meta(market)}


@api.get("/mandates/{client_id}")
async def mandate(client_id: str) -> dict[str, Any]:
    try:
        doc = store.document(f"mandate_{client_id}")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"doc_id": doc.doc_id, "title": doc.title, "text": doc.text}


@api.get("/chunks/{chunk_id:path}")
async def chunk(chunk_id: str) -> dict[str, Any]:
    from app.rag.index import get_index

    index = await asyncio.to_thread(get_index)
    try:
        return index.get(chunk_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown chunk {chunk_id}") from exc


# ---- runs ------------------------------------------------------------------------------------
@api.post("/runs", status_code=202)
async def start_run(body: RunRequest, request: Request) -> dict[str, Any]:
    if body.client_id not in store.accounts():
        raise HTTPException(status_code=404, detail=f"unknown client {body.client_id}")
    if not body.methods:
        raise HTTPException(status_code=422, detail="choose at least one method")
    return await request.app.state.runs.start(body)


@api.get("/runs")
async def list_runs(request: Request, limit: int = Query(30, ge=1, le=200),
                    client_id: str | None = None) -> list[dict[str, Any]]:
    docs = await request.app.state.runs.list_runs(limit, client_id)
    keep = ("id", "client_id", "client_name", "profile", "request", "status", "created_at",
            "updated_at", "trace_url", "llm", "market", "currency_symbol")
    out = []
    for d in docs:
        row = {k: d.get(k) for k in keep}
        opt = d.get("result", {}).get("optimization") or {}
        row["recommended"] = opt.get("recommended")
        row["quantum_gap"] = opt.get("quantum_gap")
        out.append(row)
    return out


@api.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    doc = await request.app.state.runs.get(run_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="run not found")
    return doc


@api.post("/runs/{run_id}/approval")
async def approve(run_id: str, body: ApprovalRequest, request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.runs.decide(run_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@api.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, after: int = 0) -> EventSourceResponse:
    service = request.app.state.runs
    if await service.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    queue = service.bus.subscribe(run_id)

    async def stream():  # noqa: ANN202
        try:
            last = after
            for event in await service.db.events(run_id, after):
                last = event["seq"]
                yield {"event": event["type"], "id": str(event["seq"]), "data": json.dumps(event)}
            doc = await service.get(run_id)
            if doc["status"] in TERMINAL | {"awaiting_approval"} and service.bus is not None:
                yield {"event": "status", "data": json.dumps({"type": "status", "data": {"status": doc["status"]}})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if event["seq"] <= last:
                    continue
                last = event["seq"]
                yield {"event": event["type"], "id": str(event["seq"]), "data": json.dumps(event)}
        finally:
            service.bus.unsubscribe(run_id, queue)

    return EventSourceResponse(stream())


# ---- system / evaluations ---------------------------------------------------------------------
@api.get("/system")
async def system(request: Request) -> dict[str, Any]:
    from app.graph.context import STEPS
    from app.graph.workflow import mermaid

    s = request.app.state.settings
    cards = {}
    for name, module in registry.AGENTS.items():
        base = registry.agent_url(s, name)
        card = module.card(base)
        cards[name] = {"name": card.name, "description": card.description, "url": base,
                       "card_url": f"{base}/.well-known/agent-card.json",
                       "skills": [{"id": sk.id, "name": sk.name, "description": sk.description}
                                  for sk in card.skills]}
    async with MCPHub(s.mcp_transport, s.mcp_timeout_seconds) as hub:  # discovery: tools/list
        tools = hub.catalog()
    return {
        "graph_mermaid": mermaid(),
        "steps": [{"key": k, "number": v.number, "title": v.title, "plain": v.plain, "type": v.as_type}
                  for k, v in STEPS.items()],
        "a2a_agents": cards,
        "mcp_servers": tools,
        "tool_permissions": {a: sorted(p) for a, p in AGENT_TOOL_ACL.items()},
        "scores": [{"name": sp.name, "type": sp.data_type, "description": sp.description}
                   for sp in SCORES],
        "settings": {"llm_provider": s.llm_provider, "llm_model": s.resolved_llm_model,
                     "judge": f"{s.resolved_judge_provider}:{s.resolved_judge_model}",
                     "rag_mode": s.rag_mode, "embedding_model": s.embedding_model,
                     "reranker_model": s.reranker_model, "qaoa": {"reps": s.qaoa_reps,
                     "maxiter": s.qaoa_maxiter, "shots": s.qaoa_shots, "mixer": s.qaoa_mixer},
                     "train_window": [s.train_start, s.train_end]},
    }


@api.get("/evaluations")
async def evaluations() -> dict[str, Any]:
    folder = ROOT / "experiments" / "results"
    out: dict[str, Any] = {}
    for name in ("rag_eval", "quantum_eval"):
        files = sorted(folder.glob(f"{name}_*.json"))
        if files:
            out[name] = json.loads(Path(files[-1]).read_text())
    return out
