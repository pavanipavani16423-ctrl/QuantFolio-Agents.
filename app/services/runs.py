"""Runs: start the agent graph in the background, stream progress, pause for approval, resume.

A run is one LangGraph thread (checkpointed in SQLite, so a run waiting for approval survives
a server restart) and one Langfuse trace (the resumed part joins the same trace id).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from app.config import Settings
from app.data import store
from app.data.universe import MARKETS
from app.db.database import Database
from app.graph.context import STEPS, RunContext, register, unregister
from app.graph.workflow import build_graph
from app.guardrails.pii import redact
from app.llm.gateway import LLMGateway
from app.mcp.hub import MCPHub
from app.memory import MemoryManager
from app.observability.tracing import get_tracer
from app.schemas import ApprovalRequest, RunRequest
from app.services.events import EventBus

logger = logging.getLogger(__name__)

RESULT_KEYS = ("input_guard", "intake", "memory", "research", "risk_profile", "rules", "mandate_meta",
               "optimization", "backtest", "compliance", "risk_check", "memo", "memo_facts", "evaluation",
               "trades", "approval", "execution", "preferences", "applied", "effective_rules", "revision")
LIST_KEYS = ("a2a_calls", "warnings", "decisions", "guardrails")
# steps that run again after "Change" (the re-plan starts at the optimizer)
REPLAN_STEPS = ("optimize", "backtest", "check", "report", "evaluate", "trades", "approval")


class ConflictError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunService:
    def __init__(self, settings: Settings, db: Database, bus: EventBus, checkpointer: Any,
                 max_concurrent: int = 2) -> None:
        self.settings = settings
        self.db = db
        self.bus = bus
        self.graph = build_graph(checkpointer)
        self._docs: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._scoring: dict[str, asyncio.Task] = {}  # background RAGAS scoring per run
        self._limit = asyncio.Semaphore(max_concurrent)
        self.memory = MemoryManager(db, settings)
        self._decide_locks: dict[str, asyncio.Lock] = {}

    # ---- lifecycle -------------------------------------------------------------------------
    async def recover(self) -> None:
        """Runs that were executing when the server stopped cannot continue mid-step."""
        for doc in await self.db.runs_with_status("running"):
            doc["status"] = "failed"
            doc["error"] = "the server restarted while this run was executing"
            await self.db.save_run(doc)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro) -> asyncio.Task:  # noqa: ANN001
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _spawn_scoring(self, doc: dict[str, Any], coro) -> None:  # noqa: ANN001
        self._scoring[doc["id"]] = self._spawn(self._background_scores(doc, coro))

    # ---- public API ------------------------------------------------------------------------
    async def start(self, req: RunRequest, requested_by: str = "api") -> dict[str, Any]:
        account = store.account(req.client_id)
        market = MARKETS[account["market"]]
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        llm = LLMGateway(self.settings)
        # personal data is removed before the request is stored, traced or sent to a model
        request, pii = redact(req.request) if self.settings.guardrails_enabled else (req.request, {})
        doc = {
            "id": run_id, "client_id": req.client_id, "client_name": account["name"],
            "profile": account["profile"], "request": request, "pii_redacted": pii,
            "market": market.code, "market_name": market.name, "currency": market.currency,
            "currency_symbol": market.symbol, "benchmark_name": market.benchmark_name,
            "research_sources": market.research_sources,
            "status": "queued", "created_at": _now(), "updated_at": _now(),
            "trace_id": None, "trace_url": None, "error": None, "blocked_reason": None,
            "llm": llm.mode, "langfuse": get_tracer().enabled,
            "steps": {k: {"key": k, "number": s.number, "title": s.plain, "status": "pending"}
                      for k, s in STEPS.items()},
            "decisions": [], "tool_calls": [], "llm_calls": [], "a2a_calls": [], "warnings": [], "guardrails": [],
            "feedback": [], "result": {"revision": 0}, "event_seq": 0,
        }
        self._docs[run_id] = doc
        await self.db.save_run(doc)
        await self.db.audit(actor=requested_by, action="run_started", run_id=run_id, client_id=req.client_id,
                            details={"pii_redacted": pii, "request_chars": len(request)})
        initial = {"run_id": run_id, "client_id": req.client_id, "market": market.code,
                   "request": request, "pii": pii, "revision": 0}
        self._spawn(self._execute(run_id, initial, resume=None))
        return doc

    async def get(self, run_id: str) -> dict[str, Any] | None:
        return self._docs.get(run_id) or await self.db.get_run(run_id)

    async def list_runs(self, limit: int = 50, client_id: str | None = None) -> list[dict[str, Any]]:
        return await self.db.list_runs(limit, client_id)

    async def decide(self, run_id: str, decision: ApprovalRequest) -> dict[str, Any]:
        if decision.resolved_action() == "change" and not (decision.changes and (
                decision.changes.remove_tickers or decision.changes.max_weight or decision.changes.lower_risk)):
            raise ConflictError("a change needs at least one of: remove a stock, a lower cap, lower risk")
        # exactly one decision per pause: a lock in this process and an atomic status change in
        # the database (two approvals at once must never resume the run twice)
        async with self._decide_locks.setdefault(run_id, asyncio.Lock()):
            doc = await self.get(run_id)
            if doc is None:
                raise KeyError(run_id)
            if doc["status"] != "awaiting_approval" or not await self.db.claim_run(run_id, "awaiting_approval", "running"):
                raise ConflictError(f"run is {doc['status']}, not awaiting approval")
            self._docs[run_id] = doc
            doc["status"] = "running"
            await self._save(doc)
        # personal data in the reviewer's note is removed before it reaches memory, audit or traces
        resume = {**decision.model_dump(mode="json"), "action": decision.resolved_action()}
        if self.settings.guardrails_enabled:
            resume["note"] = redact(resume["note"])[0] if resume.get("note") else resume.get("note")
            resume["reviewer"] = redact(resume.get("reviewer") or "advisor")[0]
        if resume["action"] == "change":
            # the proposal is replaced: stop scoring it (saves the judge's rate limit for the new one)
            stale = self._scoring.pop(run_id, None)
            if stale and not stale.done():
                stale.cancel()
            # the UI must not show the old plan while the new one is made: clear it and reset the
            # steps that will run again
            for key in ("optimization", "backtest", "compliance", "risk_check", "memo", "memo_facts",
                        "evaluation", "trades"):
                doc["result"].pop(key, None)
            for key in REPLAN_STEPS:
                doc["steps"][key] = {**doc["steps"].get(key, {"key": key}), "status": "pending",
                                     "summary": None, "seconds": None}
            await self._save(doc)
            await self._event(doc, "update", {"node": "approval", "keys": ["replan"]})
        self._spawn(self._execute(run_id, None, resume=resume))
        return doc

    # ---- execution -------------------------------------------------------------------------
    async def _save(self, doc: dict[str, Any]) -> None:
        doc["updated_at"] = _now()
        await self.db.save_run(doc)

    async def _event(self, doc: dict[str, Any], kind: str, data: dict[str, Any]) -> None:
        doc["event_seq"] += 1
        event = {"seq": doc["event_seq"], "type": kind, "data": data, "at": _now()}
        if kind == "step":
            step = doc["steps"].setdefault(data["key"], {"key": data["key"]})
            step.update({k: v for k, v in data.items() if k != "key"})
            if data["status"] == "running":
                step["started_at"] = event["at"]
                step.pop("summary", None)
                step.pop("error", None)
        elif kind == "tool_call":
            doc["tool_calls"].append(data)
        elif kind == "llm_call":
            doc["llm_calls"].append(data)
        elif kind == "decision":
            doc["decisions"].append({**data, "at": event["at"]})
        await self.db.add_event(doc["id"], event["seq"], kind, data)
        self.bus.publish(doc["id"], event)
        if kind in ("step", "status"):
            await self._save(doc)

    def _merge(self, doc: dict[str, Any], update: dict[str, Any]) -> list[str]:
        changed = []
        for key, value in update.items():
            if key in RESULT_KEYS:
                if value is None:
                    doc["result"].pop(key, None)
                else:
                    doc["result"][key] = value
                changed.append(key)
            elif key in ("a2a_calls", "warnings", "feedback", "guardrails"):
                doc.setdefault(key, []).extend(value or [])
                if key == "guardrails":
                    changed.append(key)
        return changed

    async def _execute(self, run_id: str, initial: dict | None, resume: dict | None) -> None:
        doc = self._docs[run_id]
        tracer = get_tracer()
        llm = LLMGateway(self.settings)

        async def emit(kind: str, data: dict[str, Any]) -> None:
            await self._event(doc, kind, data)

        async def record_tool(info: dict[str, Any]) -> None:
            await emit("tool_call", info)

        async def record_llm(info: dict[str, Any]) -> None:
            await emit("llm_call", info)

        llm.recorder = record_llm
        ctx = RunContext(run_id=run_id, settings=self.settings, tracer=tracer, llm=llm, emit=emit,
                         memory=self.memory, audit=self.db.audit,
                         spawn=lambda coro: self._spawn_scoring(doc, coro))
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 80}
        async with self._limit:
            doc["status"] = "running"
            await self._event(doc, "status", {"status": "running"})
            register(ctx)
            try:
                async with MCPHub(self.settings.mcp_transport, self.settings.mcp_timeout_seconds,
                                  recorder=record_tool, max_calls=self.settings.max_tool_calls_per_run) as hub:
                    ctx.hub = hub
                    with tracer.run_trace(
                        name="portfolio-run", run_id=run_id,
                        input={"request": doc["request"], "client": doc["client_id"],
                               "resume": resume},
                        user_id=doc["client_id"], session_id=f"client-{doc['client_id']}",
                        tags=[doc["client_id"], doc["profile"], f"llm:{self.settings.llm_provider}",
                              "resume" if resume else "start"],
                        metadata={"run_id": run_id, "market": doc["market"],
                                  "guardrails": str(self.settings.guardrails_enabled)},
                        trace_id=doc.get("trace_id"),
                    ) as root:
                        ctx.trace_id = tracer.current_trace_id() or doc.get("trace_id")
                        if ctx.trace_id and not doc.get("trace_id"):
                            doc["trace_id"] = ctx.trace_id
                            doc["trace_url"] = tracer.trace_url(ctx.trace_id)
                        payload = Command(resume=resume) if resume is not None else initial
                        interrupted = False
                        async with asyncio.timeout(self.settings.run_timeout_seconds):
                            async for chunk in self.graph.astream(payload, config, stream_mode="updates"):
                                for node, update in chunk.items():
                                    if node == "__interrupt__":
                                        interrupted = True
                                        continue
                                    changed = self._merge(doc, update or {})
                                    if changed:
                                        await self._event(doc, "update", {"node": node, "keys": changed})
                        memo = doc["result"].get("memo") or {}
                        root.update(output={"status": "awaiting_approval" if interrupted else "completed",
                                            "headline": memo.get("headline"),
                                            "recommended": (doc["result"].get("optimization") or {}).get("recommended")})
                doc["status"] = self._final_status(doc, interrupted)
                doc["blocked_reason"] = self._blocked_reason(doc) if doc["status"] == "blocked" else None
            except Exception as exc:  # noqa: BLE001 - the run fails; the server keeps going
                logger.exception("run %s failed", run_id)
                doc["status"] = "failed"
                doc["error"] = f"{type(exc).__name__}: {exc}"[:1000]
            finally:
                unregister(run_id)
                await asyncio.to_thread(tracer.flush)  # a network drain: off the event loop
            await self._event(doc, "status", {"status": doc["status"], "error": doc.get("error")})

    async def _background_scores(self, doc: dict[str, Any], coro) -> None:  # noqa: ANN001
        """Merge the RAGAS scores into the run when the background judge finishes."""
        try:
            update = await coro
        except asyncio.CancelledError:
            coro.close() if hasattr(coro, "close") else None
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("background scoring failed for %s", doc["id"])
            update = {"scores": {}, "judge": None, "notes": [f"{type(exc).__name__}: {exc}"[:300]],
                      "ragas_status": "failed", "revision": doc["result"].get("revision", 0)}
        finally:
            await asyncio.to_thread(get_tracer().flush)
        evaluation = doc["result"].get("evaluation")
        # a newer proposal (after "Change") has its own scoring; drop stale results
        if not evaluation or evaluation.get("revision", 0) != update.get("revision", 0):
            return
        evaluation["scores"].update(update["scores"])
        evaluation.update({k: update[k] for k in ("judge", "notes", "ragas_status")})
        await self._event(doc, "update", {"node": "evaluate", "keys": ["evaluation"]})
        await self._save(doc)

    @staticmethod
    def _final_status(doc: dict[str, Any], interrupted: bool) -> str:
        result = doc["result"]
        if interrupted:
            return "awaiting_approval"
        if result.get("execution") is not None:
            return "executed"
        if result.get("approval") is not None:
            return "approved" if result["approval"].get("approved") else "rejected"
        if (result.get("input_guard") or {}).get("blocked"):
            return "blocked"
        if result.get("compliance") and not result["compliance"]["passed"]:
            return "blocked"
        if result.get("trades") and not result["trades"].get("allowed", True):
            return "blocked"
        return "completed"

    @staticmethod
    def _blocked_reason(doc: dict[str, Any]) -> str:
        result = doc["result"]
        guard = result.get("input_guard") or {}
        if guard.get("blocked"):
            return f"The safety check stopped this request: {guard.get('reason')}"
        if result.get("compliance") and not result["compliance"]["passed"]:
            failed = [c["detail"] for c in result["compliance"]["checks"] if not c["passed"]]
            return "The plan breaks a client rule: " + "; ".join(failed)
        failed = [c["detail"] for c in (result.get("trades") or {}).get("limits", []) if not c["passed"]]
        return "The orders break a broker limit: " + "; ".join(failed)
