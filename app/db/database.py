"""Async SQLAlchemy storage.

* runs + run_events       one JSON document per run and its event log (the UI's source)
* client_preferences      semantic + procedural memory (what advisors taught the agents)
* episodes                episodic memory (what happened in earlier reviews of a client)
* research_cache          semantic cache of checked research answers
* audit_log               append-only, hash-chained record of every decision

SQLite by default; set DATABASE_URL=postgresql+asyncpg://... for PostgreSQL.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.urls import sqlalchemy_url


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True)
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EventRow(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PreferenceRow(Base):
    """Something an advisor taught the agents about a client (learned from a review)."""

    __tablename__ = "client_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # exclude_ticker | max_weight | lower_risk | note
    value: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(80), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "client_id": self.client_id, "kind": self.kind, "value": self.value,
                "reason": self.reason, "reviewer": self.reviewer, "run_id": self.run_id,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class EpisodeRow(Base):
    """One finished review of a client: what was proposed and what the person decided."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    outcome: Mapped[str] = mapped_column(String(20))  # approved | rejected | changed
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "client_id": self.client_id, "run_id": self.run_id, "outcome": self.outcome,
                "summary": self.summary, "data": self.data,
                "created_at": self.created_at.isoformat() if self.created_at else None}


class ResearchCacheRow(Base):
    __tablename__ = "research_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(200), index=True)  # market | tickers | index hash
    question: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class AuditRow(Base):
    """Tamper-evident: each row stores the hash of the previous row and of itself."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(40))
    run_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "at": self.at, "run_id": self.run_id, "client_id": self.client_id,
                "actor": self.actor, "action": self.action, "details": self.details,
                "prev_hash": self.prev_hash, "hash": self.hash}


GENESIS = "0" * 64


def audit_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    payload = json.dumps({k: entry[k] for k in ("at", "run_id", "client_id", "actor", "action", "details")},
                         sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


class Database:
    def __init__(self, url: str) -> None:
        url, connect_args = sqlalchemy_url(url)
        # Neon suspends idle databases and closes their connections: check before use, recycle
        extra = {"pool_pre_ping": True, "pool_recycle": 300} if connect_args else {}
        self.engine = create_async_engine(url, future=True, connect_args=connect_args, **extra)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self._audit_lock = asyncio.Lock()

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def save_run(self, doc: dict[str, Any]) -> None:
        async with self.sessions() as s:
            row = await s.get(RunRow, doc["id"])
            if row is None:
                row = RunRow(id=doc["id"], client_id=doc["client_id"], request=doc["request"],
                             status=doc["status"], document=doc)
                s.add(row)
            row.status = doc["status"]
            row.trace_id = doc.get("trace_id")
            row.error = doc.get("error")
            row.document = doc
            row.updated_at = _now()
            await s.commit()

    async def claim_run(self, run_id: str, expected: str, new: str) -> bool:
        """Atomic compare-and-set of a run's status (one decision per approval pause, even
        across processes)."""
        async with self.sessions() as s:
            result = await s.execute(update(RunRow).where(RunRow.id == run_id, RunRow.status == expected)
                                     .values(status=new, updated_at=_now()))
            await s.commit()
            return (result.rowcount or 0) == 1

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self.sessions() as s:
            row = await s.get(RunRow, run_id)
            return dict(row.document) if row else None

    async def list_runs(self, limit: int = 50, client_id: str | None = None) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
            if client_id:
                q = q.where(RunRow.client_id == client_id)
            return [dict(r.document) for r in (await s.execute(q)).scalars()]

    async def runs_with_status(self, status: str) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = select(RunRow).where(RunRow.status == status)
            return [dict(r.document) for r in (await s.execute(q)).scalars()]

    async def add_event(self, run_id: str, seq: int, type_: str, data: dict[str, Any]) -> None:
        async with self.sessions() as s:
            s.add(EventRow(run_id=run_id, seq=seq, type=type_, data=data))
            await s.commit()

    async def events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = (select(EventRow).where(EventRow.run_id == run_id, EventRow.seq > after)
                 .order_by(EventRow.seq))
            return [{"seq": e.seq, "type": e.type, "data": e.data,
                     "at": e.created_at.isoformat() if e.created_at else None}
                    for e in (await s.execute(q)).scalars()]

    # ---- learned client preferences --------------------------------------------------------
    async def add_preferences(self, rows: list[dict[str, Any]]) -> None:
        async with self.sessions() as s:
            for row in rows:
                # one active value per (client, kind, value): re-teaching the same thing is a no-op
                existing = (await s.execute(select(PreferenceRow).where(
                    PreferenceRow.client_id == row["client_id"], PreferenceRow.kind == row["kind"],
                    PreferenceRow.value == row["value"], PreferenceRow.active == 1))).scalars().first()
                if existing is None:
                    s.add(PreferenceRow(**row))
            await s.commit()

    async def preferences(self, client_id: str) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = (select(PreferenceRow).where(PreferenceRow.client_id == client_id, PreferenceRow.active == 1)
                 .order_by(PreferenceRow.created_at))
            return [r.to_dict() for r in (await s.execute(q)).scalars()]

    async def forget_preference(self, client_id: str, pref_id: int) -> bool:
        async with self.sessions() as s:
            row = await s.get(PreferenceRow, pref_id)
            if row is None or row.client_id != client_id:
                return False
            row.active = 0
            await s.commit()
            return True

    async def count_runs(self) -> int:
        async with self.sessions() as s:
            return int((await s.execute(select(func.count(RunRow.id)))).scalar_one())

    # ---- episodic memory -------------------------------------------------------------------
    async def add_episode(self, row: dict[str, Any]) -> None:
        async with self.sessions() as s:
            s.add(EpisodeRow(**row))
            await s.commit()

    async def episodes(self, client_id: str, limit: int = 3) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = (select(EpisodeRow).where(EpisodeRow.client_id == client_id)
                 .order_by(EpisodeRow.created_at.desc(), EpisodeRow.id.desc()).limit(limit))
            return [r.to_dict() for r in (await s.execute(q)).scalars()]

    async def forget_client(self, client_id: str) -> dict[str, int]:
        """Right to be forgotten: remove a client's learned memory (the audit log is kept)."""
        async with self.sessions() as s:
            prefs = (await s.execute(delete(PreferenceRow).where(PreferenceRow.client_id == client_id))).rowcount
            eps = (await s.execute(delete(EpisodeRow).where(EpisodeRow.client_id == client_id))).rowcount
            await s.commit()
        return {"preferences": prefs or 0, "episodes": eps or 0}

    # ---- research cache --------------------------------------------------------------------
    async def cache_candidates(self, key: str, max_age_hours: float) -> list[dict[str, Any]]:
        cutoff = _now() - timedelta(hours=max_age_hours)
        async with self.sessions() as s:
            q = (select(ResearchCacheRow).where(ResearchCacheRow.key == key, ResearchCacheRow.created_at >= cutoff)
                 .order_by(ResearchCacheRow.created_at.desc()).limit(50))
            return [{"id": r.id, "question": r.question, "embedding": r.embedding, "result": r.result,
                     "run_id": r.run_id, "created_at": r.created_at.isoformat() if r.created_at else None}
                    for r in (await s.execute(q)).scalars()]

    async def cache_put(self, row: dict[str, Any]) -> None:
        async with self.sessions() as s:
            s.add(ResearchCacheRow(**row))
            await s.commit()

    async def cache_hit(self, row_id: int) -> None:
        async with self.sessions() as s:
            row = await s.get(ResearchCacheRow, row_id)
            if row is not None:
                row.hits += 1
                await s.commit()

    async def cache_size(self) -> int:
        async with self.sessions() as s:
            return int((await s.execute(select(func.count(ResearchCacheRow.id)))).scalar_one())

    # ---- audit log -------------------------------------------------------------------------
    async def audit(self, *, actor: str, action: str, run_id: str | None = None,
                    client_id: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = {"at": datetime.now(UTC).isoformat(), "run_id": run_id, "client_id": client_id,
                 "actor": actor[:80], "action": action[:60],
                 "details": json.loads(json.dumps(details or {}, default=str))}
        async with self._audit_lock, self.sessions() as s:
            last = (await s.execute(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1))).scalars().first()
            prev = last.hash if last else GENESIS
            row = AuditRow(**entry, prev_hash=prev, hash=audit_hash(prev, entry))
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def audit_entries(self, run_id: str | None = None, client_id: str | None = None,
                            limit: int = 200) -> list[dict[str, Any]]:
        async with self.sessions() as s:
            q = select(AuditRow).order_by(AuditRow.seq).limit(limit)
            if run_id:
                q = q.where(AuditRow.run_id == run_id)
            if client_id:
                q = q.where(AuditRow.client_id == client_id)
            return [r.to_dict() for r in (await s.execute(q)).scalars()]

    async def verify_audit(self) -> dict[str, Any]:
        """Recompute the chain; any edited, inserted or deleted row breaks it."""
        async with self.sessions() as s:
            rows = list((await s.execute(select(AuditRow).order_by(AuditRow.seq))).scalars())
        prev = GENESIS
        for row in rows:
            if row.prev_hash != prev or row.hash != audit_hash(prev, row.to_dict()):
                return {"valid": False, "entries": len(rows), "broken_at": row.seq}
            prev = row.hash
        return {"valid": True, "entries": len(rows), "broken_at": None, "head": prev}
