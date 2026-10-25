"""MCP server: market data and risk statistics from the committed price snapshot."""

from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.data import store
from app.data.universe import BY_TICKER, MARKETS, market_of_tickers, universe
from app.quant.stats import market_stats, portfolio_risk


def _check(tickers: list[str]) -> tuple[list[str], str]:
    """Validate tickers and return them with their (single) market."""
    tickers = [t.upper() for t in tickers]
    unknown = [t for t in tickers if t not in BY_TICKER]
    if unknown:
        raise ToolError(f"unknown tickers: {unknown}")
    if not tickers:
        raise ToolError("no tickers given")
    try:
        return tickers, market_of_tickers(tickers)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def list_universe(market: str = "US") -> dict[str, Any]:
    if market not in MARKETS:
        raise ToolError(f"market must be one of {sorted(MARKETS)}")
    meta = store.prices_meta(market)
    m = MARKETS[market]
    return {
        "market": market, "currency": m.currency, "benchmark": m.benchmark,
        "assets": [{"ticker": a.ticker, "name": a.name, "sector": a.sector} for a in universe(market)],
        "prices": {"start": meta["start"], "end": meta["end"], "source": meta["source"]},
    }


async def get_market_stats(tickers: list[str], start: str, end: str) -> dict[str, Any]:
    tickers, market = _check(tickers)
    bench = MARKETS[market].benchmark
    stats = await anyio.to_thread.run_sync(
        lambda: market_stats(store.prices(market), tickers, bench, start, end)
    )
    out = stats.to_dict()
    out["sectors"] = {t: BY_TICKER[t].sector for t in tickers}
    out["market"] = market
    return out


async def get_portfolio_risk(weights: dict[str, float], start: str, end: str) -> dict[str, Any]:
    _, market = _check(list(weights))
    if abs(sum(weights.values()) - 1) > 1e-3:
        raise ToolError("weights must sum to 1")
    bench = MARKETS[market].benchmark
    return await anyio.to_thread.run_sync(
        lambda: portfolio_risk(weights, store.prices(market), bench, start, end)
    )


async def get_latest_prices(tickers: list[str]) -> dict[str, Any]:
    tickers, market = _check(tickers)
    frame = store.prices(market)
    return {"date": str(frame.index[-1].date()),
            "prices": {t: float(frame[t].iloc[-1]) for t in tickers}}


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-market-data",
                       instructions="Daily prices (Yahoo Finance snapshot) and risk statistics.")
    server.tool(description="List a market's investable universe (US or IN), sectors and price range.")(list_universe)
    server.tool(description="Expected returns, Ledoit-Wolf covariance, volatility, beta, VaR and "
                "drawdown for tickers over a date window.")(get_market_stats)
    server.tool(description="Risk of a weighted portfolio (volatility, beta, VaR, CVaR, drawdown).")(get_portfolio_risk)
    server.tool(description="Latest close prices.")(get_latest_prices)
    return server


if __name__ == "__main__":
    build_server().run()
