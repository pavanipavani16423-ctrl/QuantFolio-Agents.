"""FastAPI application: REST + SSE API for the UI, and the hosted A2A agents."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.a2a import registry
from app.api import routes
from app.config import Settings, get_settings
from app.db.database import Database
from app.logging_setup import setup_logging
from app.observability.tracing import get_tracer
from app.services.events import EventBus
from app.services.runs import RunService

logger = logging.getLogger(__name__)


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
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as checkpointer:
            service = RunService(settings, db, EventBus(), checkpointer)
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
        version="0.1.0",
        description="Multi-agent investment research and portfolio rebalancing: LangGraph "
        "supervisor, A2A risk and compliance agents, MCP tools, hybrid RAG, QAOA, Langfuse, RAGAS.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    app.include_router(routes.public)
    app.include_router(routes.api, prefix="/api/v1")
    registry.mount_agents(app, settings)
    return app


app = create_app()
