"""MCP server: portfolio selection (classical, QAOA, hybrid), weights and backtests.

Permission boundary: qubits, depth, shots and iterations are capped here whatever the caller
asks for, so an agent cannot request a simulation that exhausts the host.
"""

import os
import time
from typing import Any

import anyio
import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from app.data import store
from app.quant.backtest import backtest
from app.quant.portfolio import (
    local_search,
    optimize_weights,
    select_exact,
    select_greedy,
    selection_problem,
)
from app.quantum.qaoa_solver import QAOAConfig, run_qaoa

MAX_QUBITS = int(os.environ.get("QAOA_MAX_QUBITS", "20"))
MAX_REPS, MAX_SHOTS, MAX_ITER = 4, 8192, 300


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
    try:
        return selection_problem(p.tickers, p.sectors, p.mu, p.cov, p.k, p.risk_aversion,
                                 p.max_sector_weight)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def select_classical(problem: Problem) -> dict[str, Any]:
    sp = _problem(problem)

    def run() -> dict[str, Any]:
        exact = select_exact(sp)
        greedy = select_greedy(sp)
        return {"exact": exact.to_dict(), "greedy": greedy.to_dict()}

    try:
        return await anyio.to_thread.run_sync(run)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def select_quantum(problem: Problem, reps: int = 2, maxiter: int = 60, shots: int = 2048,
                         mixer: str = "xy", seed: int = 7) -> dict[str, Any]:
    sp = _problem(problem)
    if sp.n > MAX_QUBITS:
        raise ToolError(f"{sp.n} qubits exceeds this server's limit of {MAX_QUBITS}")
    if mixer not in ("x", "xy"):
        raise ToolError("mixer must be 'x' or 'xy'")
    config = QAOAConfig(reps=min(max(reps, 1), MAX_REPS), maxiter=min(max(maxiter, 1), MAX_ITER),
                        shots=min(max(shots, 64), MAX_SHOTS), mixer=mixer, hamming_weight=sp.k,
                        seed=seed, top_k=128)

    def run() -> dict[str, Any]:
        started = time.perf_counter()
        result = run_qaoa(sp.qubo(with_penalty=(mixer == "x")), config)
        feasible = [s for s in result.samples if sp.feasible(s.bits)]
        # without a feasible sample the hybrid step repairs from the best sample
        bits = feasible[0].bits if feasible else result.samples[0].bits
        best = {
            "selected": [sp.tickers[i] for i in np.flatnonzero(bits)],
            "bitstring": "".join(str(int(b)) for b in bits),
            "utility": sp.utility(bits) if int(bits.sum()) else None,
            "feasible": sp.feasible(bits),
        }
        top = [{"bitstring": s.bitstring, "probability": s.probability, "feasible": sp.feasible(s.bits)}
               for s in result.samples[:10]]
        data = result.to_dict()
        data.pop("samples", None)
        data.pop("convergence", None)
        return {
            "best": best,
            "qaoa": data,
            "convergence": [round(v, 6) for v in result.convergence],
            "top_samples": top,
            "feasible_in_top_samples": len(feasible),
            "seconds": round(time.perf_counter() - started, 3),
        }

    return await anyio.to_thread.run_sync(run)


async def refine_hybrid(problem: Problem, start_bitstring: str) -> dict[str, Any]:
    sp = _problem(problem)
    if len(start_bitstring) != sp.n or set(start_bitstring) - {"0", "1"}:
        raise ToolError("start_bitstring must be a 0/1 string with one character per ticker")

    def run() -> dict[str, Any]:
        started = time.perf_counter()
        bits = np.array([int(c) for c in start_bitstring], dtype=np.int8)
        repaired = False
        if not sp.feasible(bits):  # fix the count first: drop worst / add best by utility
            repaired = True
            while bits.sum() > sp.k:
                ones = np.flatnonzero(bits)
                drop = max(ones, key=lambda i: sp.utility(np.where(np.arange(sp.n) == i, 0, bits)))
                bits[drop] = 0
            while bits.sum() < sp.k:
                zeros = np.flatnonzero(bits == 0)
                add = max(zeros, key=lambda i: sp.utility(np.where(np.arange(sp.n) == i, 1, bits)))
                bits[add] = 1
        refined, moves = local_search(sp, bits)
        return {
            "selected": [sp.tickers[i] for i in np.flatnonzero(refined)],
            "bitstring": "".join(str(int(b)) for b in refined),
            "utility": sp.utility(refined),
            "feasible": sp.feasible(refined),
            "start_utility": sp.utility(bits),
            "repaired": repaired,
            "swap_moves": moves,
            "seconds": round(time.perf_counter() - started, 4),
        }

    return await anyio.to_thread.run_sync(run)


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
                       instructions="Choose k stocks (exact search, greedy, QAOA, hybrid), then "
                       "mean-variance weights, then an out-of-sample backtest.")
    server.tool(description="Exact (exhaustive) and greedy k-of-n stock selection.")(select_classical)
    server.tool(description="QAOA k-of-n stock selection on the local simulator (XY or X mixer).")(select_quantum)
    server.tool(description="Hybrid: repair + 1-swap local search starting from a QAOA bitstring.")(refine_hybrid)
    server.tool(description="Long-only mean-variance weights for the selected stocks under the "
                "mandate limits.")(optimize_portfolio_weights)
    server.tool(description="Out-of-sample buy-and-hold backtest of named portfolios.")(run_backtest)
    return server


if __name__ == "__main__":
    build_server().run()
