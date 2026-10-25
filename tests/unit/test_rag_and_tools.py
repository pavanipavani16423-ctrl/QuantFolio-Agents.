import pytest

from app.data import store
from app.mcp.hub import MCPHub, MCPPermissionError, MCPToolError, is_allowed
from app.mcp.servers import broker
from app.rag.chunking import chunk_document
from app.rag.index import get_index, tokenize


def test_tokenize_keeps_numbers_and_drops_stopwords() -> None:
    assert tokenize("What was Apple's revenue in 2025?") == ["apple's", "revenue", "2025"]


def test_chunk_ids_are_stable_and_carry_context() -> None:
    doc = store.document("mandate_C-102")
    a, b = chunk_document(doc), chunk_document(doc)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert all("GreenLeaf Foundation" in c.header for c in a)


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid", "hybrid_rerank"])
def test_every_mode_finds_the_mandate_section(mode: str) -> None:
    hits, trace = get_index().search("no single holding may exceed", k=3, mode=mode,
                                     doc_types=["mandate"], client_id="C-102")
    assert hits and all(h.chunk.client_id == "C-102" for h in hits)
    assert any("Position limits" in h.chunk.text for h in hits)
    assert trace.filtered_pool == 7


def test_acl_is_least_privilege() -> None:
    assert is_allowed("trader_agent", "broker", "execute_orders")
    assert not is_allowed("research_agent", "broker", "execute_orders")
    assert not is_allowed("compliance_agent", "optimizer", "select_quantum")


@pytest.mark.anyio
async def test_toolbox_denies_tools_outside_the_acl() -> None:
    async with MCPHub("inprocess") as hub:
        with pytest.raises(MCPPermissionError):
            await hub.toolbox("research_agent").call("broker", "execute_orders", client_id="C-101",
                                                    trades=[], approval_id="x", approved_by="y")
        with pytest.raises(MCPToolError):  # the server validates input too
            await hub.toolbox("risk_agent").call("market", "get_market_stats", tickers=["NOPE"],
                                                 start="2024-01-02", end="2026-04-30")


@pytest.mark.anyio
async def test_broker_needs_approval_and_is_idempotent() -> None:
    broker.reset_account("C-101")
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        await broker.execute_orders("C-101", [], approval_id="", approved_by="")
    preview = await broker.preview_rebalance("C-101", {"KO": 0.5, "PG": 0.5})
    assert preview["trades"]
    first = await broker.execute_orders("C-101", preview["trades"], approval_id="test-1", approved_by="tester")
    again = await broker.execute_orders("C-101", preview["trades"], approval_id="test-1", approved_by="tester")
    assert not first["replayed"] and again["replayed"]
    assert set(first["account"]["positions"]) == {"KO", "PG"}
    broker.reset_account("C-101")
