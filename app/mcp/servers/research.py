"""MCP server: hybrid RAG search over SEC filings, financial facts and client mandates."""

from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.rag.index import MODES, corpus_stats, get_index

MAX_K = 20


async def search_documents(
    query: str,
    k: int = 6,
    mode: str = "hybrid_rerank",
    tickers: list[str] | None = None,
    doc_types: list[str] | None = None,
    client_id: str | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise ToolError("empty query")
    if mode not in MODES:
        raise ToolError(f"mode must be one of {MODES}")
    k = max(1, min(k, MAX_K))

    def run() -> dict[str, Any]:
        hits, trace = get_index().search(query, k=k, mode=mode, tickers=tickers,
                                         doc_types=doc_types, client_id=client_id, market=market)
        return {
            "query": query,
            "mode": mode,
            "hits": [h.to_dict() for h in hits],
            "trace": {
                "filtered_pool": trace.filtered_pool,
                "bm25_top": trace.bm25_top,
                "dense_top": trace.dense_top,
                "fused_top": trace.fused_top,
                "timings_ms": trace.timings_ms,
            },
        }

    return await anyio.to_thread.run_sync(run)


async def get_chunk(chunk_id: str) -> dict[str, Any]:
    index = await anyio.to_thread.run_sync(get_index)
    try:
        chunk = index.get(chunk_id)
    except KeyError:
        raise ToolError(f"unknown chunk {chunk_id!r}") from None
    return chunk.to_dict()


async def corpus_info() -> dict[str, Any]:
    return corpus_stats()


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-research",
                       instructions="Hybrid search (BM25 + dense + RRF + cross-encoder rerank) over "
                       "10-K risk factors and MD&A, SEC XBRL facts and client mandates.")
    server.tool(description="Search the document corpus. Filters: tickers, market (US, IN), "
                "doc_types (US: risk_factors, mdna; India: ar_mdna, ar_risk, brsr; both: facts; "
                "mandate), client_id.")(search_documents)
    server.tool(description="Fetch one chunk by id.")(get_chunk)
    server.tool(description="Corpus size by document type.")(corpus_info)
    return server


if __name__ == "__main__":
    build_server().run()
