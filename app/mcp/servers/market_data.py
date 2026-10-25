"""MCP server: market data and risk statistics from the committed price snapshot."""

from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.data import store
from app.data.universe import BENCHMARK, BY_TICKER, UNIVERSE
from app.quant.stats import market_stats, portfolio_risk


def _check(tickers: list[str]) -> list[str]:
    tickers = [t.upper() for t in tickers]
    unknown = [t for t in tickers if t not in BY_TICKER]
    if unknown:
        raise ToolError(f"unknown tickers: {unknown}")
    if not tickers:
        raise ToolError("no tickers given")
    return tickers


async def list_universe() -> dict[str, Any]:
    meta = store.prices_meta()
    return {
        "assets": [{"ticker": a.ticker, "name": a.name, "sector": a.sector} for a in UNIVERSE],
        "benchmark": BENCHMARK,
        "prices": {"start": meta["start"], "end": meta["end"], "source": meta["source"]},
    }


async def get_market_stats(tickers: list[str], start: str, end: str) -> dict[str, Any]:
    tickers = _check(tickers)
    stats = await anyio.to_thread.run_sync(
        lambda: market_stats(store.prices(), tickers, BENCHMARK, start, end)
    )
    out = stats.to_dict()
    out["sectors"] = {t: BY_TICKER[t].sector for t in tickers}
    return out


async def get_portfolio_risk(weights: dict[str, float], start: str, end: str) -> dict[str, Any]:
    _check(list(weights))
    if abs(sum(weights.values()) - 1) > 1e-3:
        raise ToolError("weights must sum to 1")
    return await anyio.to_thread.run_sync(
        lambda: portfolio_risk(weights, store.prices(), BENCHMARK, start, end)
    )


async def get_latest_prices(tickers: list[str]) -> dict[str, Any]:
    tickers = _check(tickers)
    frame = store.prices()
    return {"date": str(frame.index[-1].date()),
            "prices": {t: float(frame[t].iloc[-1]) for t in tickers}}


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-market-data",
                       instructions="Daily prices (Yahoo Finance snapshot) and risk statistics.")
    server.tool(description="List the investable universe, sectors and the price date range.")(list_universe)
    server.tool(description="Expected returns, Ledoit-Wolf covariance, volatility, beta, VaR and "
                "drawdown for tickers over a date window.")(get_market_stats)
    server.tool(description="Risk of a weighted portfolio (volatility, beta, VaR, CVaR, drawdown).")(get_portfolio_risk)
    server.tool(description="Latest close prices.")(get_latest_prices)
    return server


if __name__ == "__main__":
    build_server().run()
