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

    async def count_runs(self) -> int:
        async with self.sessions() as s:
            return int((await s.execute(select(func.count(RunRow.id)))).scalar_one())
