"""FastAPI application: REST + SSE API for the UI, and the hosted A2A agents."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.a2a import registry
from app.api import routes
from app.config import Settings, get_settings
from app.db.database import Database
from app.db.urls import is_postgres, libpq_url
from app.logging_setup import setup_logging
from app.observability.tracing import get_tracer
from app.security.http import A2AAuthMiddleware, HardeningMiddleware, RateLimiter
from app.services.events import EventBus
from app.services.runs import RunService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_checkpointer(settings: Settings):  # noqa: ANN201
    """Where paused runs live: a SQLite file on a laptop; Postgres (Neon) when DATABASE_URL is
    Postgres, so a run waiting for approval survives a restart or a redeploy."""
    if not is_postgres(settings.database_url):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # 28 MB: only when it is used

        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as saver:
            yield saver
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    async with AsyncConnectionPool(libpq_url(settings.database_url), min_size=1, max_size=5, open=False,
                                   kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                                   check=AsyncConnectionPool.check_connection) as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        yield saver


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db = Database(settings.database_url)
        await db.create_all()
        tracer = get_tracer()
        await asyncio.to_thread(tracer.setup)  # Langfuse score configs (network)
        async with open_checkpointer(settings) as checkpointer:
            service = RunService(settings, db, EventBus(), checkpointer, settings.max_concurrent_runs)
            await service.recover()
            app.state.settings = settings
            app.state.db = db
            app.state.runs = service
            app.state.index_ready = False

            async def warm_index() -> None:
                from app.rag.index import get_index

                await asyncio.to_thread(get_index)
                app.state.index_ready = True
                logger.info("RAG index ready")

            warm = asyncio.create_task(warm_index())
            logger.info("QuantFolio API ready (LLM: %s, Langfuse: %s)", settings.llm_provider,
                        "on" if tracer.enabled else "off")
            try:
                yield
            finally:
                warm.cancel()
                await service.shutdown()
                tracer.flush()
                await db.dispose()

    app = FastAPI(
        title="QuantFolio Agents API",
        version="0.2.0",
        description="Multi-agent investment research and portfolio rebalancing: LangGraph "
        "supervisor, A2A risk and compliance agents, MCP tools, hybrid RAG, guardrails, memory, "
        "human approval, Langfuse, RAGAS.",
        lifespan=lifespan,
    )
    app.state.run_limiter = RateLimiter(settings.rate_limit_runs, settings.rate_limit_window_seconds)
    app.add_middleware(A2AAuthMiddleware, api_key=settings.api_key.get_secret_value() if settings.api_key else None,
                       limiter=RateLimiter(settings.rate_limit_runs * 10, settings.rate_limit_window_seconds))
    app.add_middleware(HardeningMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_origin_regex=settings.cors_origin_regex, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])
    app.include_router(routes.public)
    app.include_router(routes.api, prefix="/api/v1")
    registry.mount_agents(app, settings)
    return app


app = create_app()
