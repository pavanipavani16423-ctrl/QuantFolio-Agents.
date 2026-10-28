"""MCP server: stock selection, mean-variance weights and out-of-sample backtests.

Permission boundary: the problem size is capped here whatever the caller asks for, so an
agent cannot request a search that exhausts the host.
"""

import os
from typing import Any

import anyio
import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from app.data import store
from app.quant.backtest import backtest
from app.quant.portfolio import optimize_weights, select_best, select_greedy, selection_problem

MAX_ASSETS = int(os.environ.get("OPTIMIZER_MAX_ASSETS", "40"))


class Problem(BaseModel):
    tickers: list[str]
    sectors: list[str]
    mu: list[float]
    cov: list[list[float]]
    k: int
    risk_aversion: float
    max_sector_weight: float
    min_weight: float
    max_weight: float
    max_volatility: float


def _problem(p: Problem):  # noqa: ANN202
    if not (len(p.tickers) == len(p.sectors) == len(p.mu) == len(p.cov)):
        raise ToolError("tickers, sectors, mu and cov must have the same length")
    if len(p.tickers) > MAX_ASSETS:
        raise ToolError(f"{len(p.tickers)} assets exceeds this server's limit of {MAX_ASSETS}")
    try:
        return selection_problem(p.tickers, p.sectors, p.mu, p.cov, p.k, p.risk_aversion,
                                 p.max_sector_weight)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def select_stocks(problem: Problem) -> dict[str, Any]:
    sp = _problem(problem)

    def run() -> dict[str, Any]:
        return {"optimal": select_best(sp).to_dict(), "baseline": select_greedy(sp).to_dict()}

    try:
        return await anyio.to_thread.run_sync(run)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def optimize_portfolio_weights(problem: Problem, selected: list[str]) -> dict[str, Any]:
    unknown = set(selected) - set(problem.tickers)
    if unknown:
        raise ToolError(f"selected tickers not in problem: {sorted(unknown)}")
    idx = [problem.tickers.index(t) for t in selected]
    mu = np.array(problem.mu)[idx]
    cov = np.array(problem.cov)[np.ix_(idx, idx)]
    try:
        result = await anyio.to_thread.run_sync(lambda: optimize_weights(
            selected, [problem.sectors[i] for i in idx], mu, cov, problem.risk_aversion,
            problem.min_weight, problem.max_weight, problem.max_sector_weight, problem.max_volatility,
        ))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return result.to_dict()


async def run_backtest(portfolios: dict[str, dict[str, float]], start_after: str,
                       risk_free: float = 0.04, market: str = "US") -> dict[str, Any]:
    if not portfolios:
        raise ToolError("no portfolios")
    if market not in store.PRICE_FILES:
        raise ToolError(f"unknown market {market!r}")
    try:
        return await anyio.to_thread.run_sync(
            lambda: backtest(portfolios, store.prices(market), start_after, risk_free)
        )
    except (KeyError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def build_server() -> MCPServer:
    server = MCPServer("quantfolio-optimizer",
                       instructions="Choose k stocks (exact search, with a rule-of-thumb baseline), "
                       "then mean-variance weights, then an out-of-sample backtest.")
    server.tool(description="k-of-n stock selection: proven-optimal exhaustive search (local "
                "search for large universes) and a greedy baseline.")(select_stocks)
    server.tool(description="Long-only mean-variance weights for the selected stocks under the "
                "mandate limits.")(optimize_portfolio_weights)
    server.tool(description="Out-of-sample buy-and-hold backtest of named portfolios.")(run_backtest)
    return server


if __name__ == "__main__":
    build_server().run()
