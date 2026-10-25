"""Async SQLAlchemy storage: one row per run (a JSON document) plus its event log.

SQLite by default; set DATABASE_URL=postgresql+asyncpg://... for PostgreSQL.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(url, future=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

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
