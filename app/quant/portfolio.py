"""Portfolio construction in two steps.

Step 1 - asset selection: choose exactly k of the n allowed stocks to maximize the
equal-weight mean-variance utility

        U(S) = (1/k) sum_{i in S} mu_i - lambda (1/k^2) sum_{i,j in S} Sigma_ij

    A selection is feasible when it has exactly k assets and respects the per-sector name
    limit floor(max_sector_weight * k). Up to EXACT_LIMIT subsets (C(20,10) = 184,756) are
    searched exhaustively, so the answer is the proven optimum; larger universes fall back to
    best-improvement 1-swap local search from the greedy start (flagged as not proven).
    A greedy rule of thumb (top-k return/risk) is kept as a baseline.

Step 2 - weights: for the selected set, solve the long-only mean-variance problem

        max_w  mu^T w - lambda w^T Sigma w
        s.t.   sum w = 1, min_weight <= w_i <= max_weight, sector weight <= max_sector_weight,
               sqrt(w^T Sigma w) <= max_volatility

    with SLSQP. If the volatility limit cannot be met, the solve is repeated without it and
    the result is flagged; the compliance agent will then reject it.
"""

import itertools
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

EXACT_LIMIT = 500_000  # max subsets for exhaustive search
BLOCK = 20_000  # subsets scored at once


@dataclass
class SelectionProblem:
    tickers: list[str]
    sectors: list[str]
    mu: np.ndarray
    cov: np.ndarray
    k: int
    risk_aversion: float
    max_sector_names: int

    @property
    def n(self) -> int:
        return len(self.tickers)

    def utility(self, x: np.ndarray) -> float:
        """Equal-weight utility of one selection (x is a 0/1 vector)."""
        x = np.asarray(x, dtype=float)
        k = x.sum()
        if k == 0:
            return float("-inf")
        w = x / k
        return float(w @ self.mu - self.risk_aversion * w @ self.cov @ w)

    def feasible(self, x: np.ndarray) -> bool:
        x = np.asarray(x)
        if int(x.sum()) != self.k:
            return False
        counts: dict[str, int] = {}
        for i in np.flatnonzero(x):
            counts[self.sectors[i]] = counts.get(self.sectors[i], 0) + 1
        return max(counts.values(), default=0) <= self.max_sector_names


def selection_problem(tickers, sectors, mu, cov, k, risk_aversion, max_sector_weight) -> SelectionProblem:  # noqa: ANN001
    if not 1 <= k <= len(tickers):
        raise ValueError(f"cannot hold {k} stocks from {len(tickers)} allowed")
    return SelectionProblem(
        tickers=list(tickers), sectors=list(sectors), mu=np.asarray(mu, float),
        cov=np.asarray(cov, float), k=int(k), risk_aversion=float(risk_aversion),
        max_sector_names=max(1, math.floor(max_sector_weight * k + 1e-9)),
    )


@dataclass
class SelectionResult:
    method: str
    selected: list[str]
    bits: np.ndarray
    utility: float
    feasible: bool
    seconds: float
    details: dict

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "selected": self.selected,
            "utility": self.utility,
            "feasible": self.feasible,
            "seconds": round(self.seconds, 4),
            "details": self.details,
        }


def _result(problem: SelectionProblem, method: str, bits: np.ndarray, started: float,
            details: dict) -> SelectionResult:
    return SelectionResult(
        method=method,
        selected=[problem.tickers[i] for i in np.flatnonzero(bits)],
        bits=np.asarray(bits, dtype=np.int8),
        utility=problem.utility(bits),
        feasible=problem.feasible(bits),
        seconds=time.perf_counter() - started,
        details=details,
    )


def select_exact(problem: SelectionProblem) -> SelectionResult:
    """Exhaustive search over all k-subsets: the proven optimum.

    Subsets are scored in blocks of BLOCK, so memory stays at a few MB however many there are
    (C(20,10) = 184,756 at once would need about 200 MB, too much for a 512 MB server)."""
    started = time.perf_counter()
    total = math.comb(problem.n, problem.k)
    if total > EXACT_LIMIT:
        raise ValueError(f"{total} subsets is too many for exhaustive search")
    names = sorted(set(problem.sectors))
    onehot = np.array([[s == name for name in names] for s in problem.sectors], dtype=float)
    subsets = itertools.combinations(range(problem.n), problem.k)
    best: list[tuple[float, np.ndarray]] = []  # the two best (utility, bits), best first
    feasible_total = 0
    while block := list(itertools.islice(subsets, BLOCK)):
        combos = np.array(block, dtype=np.int64)
        X = np.zeros((len(combos), problem.n))
        np.put_along_axis(X, combos, 1.0, axis=1)
        W = X / problem.k
        utilities = W @ problem.mu - problem.risk_aversion * np.einsum("ij,ij->i", W @ problem.cov, W)
        feasible = (X @ onehot).max(axis=1) <= problem.max_sector_names
        feasible_total += int(feasible.sum())
        utilities = np.where(feasible, utilities, -np.inf)
        for i in np.argsort(-utilities)[:2]:
            if np.isfinite(utilities[i]):
                best.append((float(utilities[i]), X[i].astype(np.int8)))
        best = sorted(best, key=lambda b: -b[0])[:2]
    if not best:
        raise ValueError("no selection satisfies the sector limits")
    return _result(problem, "optimal", best[0][1], started, {
        "subsets_evaluated": int(total),
        "feasible_subsets": feasible_total,
        "optimality": "proven (exhaustive search)",
        "runner_up_utility": best[1][0] if len(best) > 1 else None,
    })


def select_greedy(problem: SelectionProblem) -> SelectionResult:
    """Naive baseline: the k best individual return/risk ratios, respecting sector counts."""
    started = time.perf_counter()
    score = problem.mu / np.sqrt(np.diag(problem.cov))
    bits = np.zeros(problem.n, dtype=np.int8)
    counts: dict[str, int] = {}
    for i in np.argsort(-score):
        if bits.sum() == problem.k:
            break
        if counts.get(problem.sectors[i], 0) < problem.max_sector_names:
            bits[i] = 1
            counts[problem.sectors[i]] = counts.get(problem.sectors[i], 0) + 1
    return _result(problem, "baseline", bits, started, {"rule": "top-k by mu/sigma"})


def local_search(problem: SelectionProblem, bits: np.ndarray, max_rounds: int = 50) -> tuple[np.ndarray, int]:
    """Best-improvement 1-swap search (swap one held asset for one not held)."""
    current = np.asarray(bits, dtype=np.int8).copy()
    current_u = problem.utility(current) if problem.feasible(current) else -np.inf
    moves = 0
    for _ in range(max_rounds):
        best_u, best_x = current_u, None
        for i in np.flatnonzero(current == 1):
            for j in np.flatnonzero(current == 0):
                cand = current.copy()
                cand[i], cand[j] = 0, 1
                if not problem.feasible(cand):
                    continue
                u = problem.utility(cand)
                if u > best_u + 1e-12:
                    best_u, best_x = u, cand
        if best_x is None:
            break
        current, current_u = best_x, best_u
        moves += 1
    return current, moves


def select_best(problem: SelectionProblem) -> SelectionResult:
    """Exact when the search space is small enough, otherwise local search from greedy."""
    if math.comb(problem.n, problem.k) <= EXACT_LIMIT:
        return select_exact(problem)
    started = time.perf_counter()
    bits, moves = local_search(problem, select_greedy(problem).bits)
    return _result(problem, "optimal", bits, started, {
        "subsets_evaluated": None, "swap_moves": moves,
        "optimality": "local optimum (1-swap search; universe too large for exhaustive search)",
    })


# ---- step 2: weights ---------------------------------------------------------------------

@dataclass
class WeightResult:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    utility: float
    volatility_limit_met: bool
    sector_weights: dict[str, float]
    status: str

    def to_dict(self) -> dict:
        return {
            "weights": {t: round(w, 6) for t, w in self.weights.items()},
            "expected_return": self.expected_return,
            "volatility": self.volatility,
            "utility": self.utility,
            "volatility_limit_met": self.volatility_limit_met,
            "sector_weights": {s: round(w, 6) for s, w in self.sector_weights.items()},
            "status": self.status,
        }


def optimize_weights(tickers, sectors, mu, cov, risk_aversion, min_weight, max_weight,  # noqa: ANN001, PLR0913
                     max_sector_weight, max_volatility) -> WeightResult:
    mu, cov = np.asarray(mu, float), np.asarray(cov, float)
    n = len(tickers)
    if n * min_weight > 1 + 1e-9 or n * max_weight < 1 - 1e-9:
        raise ValueError(f"weight bounds [{min_weight}, {max_weight}] are infeasible for {n} holdings")
    sector_idx: dict[str, list[int]] = {}
    for i, s in enumerate(sectors):
        sector_idx.setdefault(s, []).append(i)

    def neg_utility(w: np.ndarray) -> float:
        return -(w @ mu - risk_aversion * w @ cov @ w)

    def grad(w: np.ndarray) -> np.ndarray:
        return -(mu - 2 * risk_aversion * cov @ w)

    base = [{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones_like(w)}]
    for idx in sector_idx.values():
        base.append({"type": "ineq", "fun": lambda w, idx=idx: max_sector_weight - w[idx].sum()})
    vol_c = {"type": "ineq", "fun": lambda w: max_volatility**2 - w @ cov @ w,
             "jac": lambda w: -2 * cov @ w}
    bounds = [(min_weight, max_weight)] * n
    w0 = np.full(n, 1 / n)

    def solve(constraints: list) -> tuple[np.ndarray, bool]:
        res = minimize(neg_utility, w0, jac=grad, bounds=bounds, constraints=constraints,
                       method="SLSQP", options={"maxiter": 500, "ftol": 1e-12})
        w = np.clip(res.x, min_weight, max_weight)
        return w / w.sum(), bool(res.success)

    w, ok = solve([*base, vol_c])
    vol = float(np.sqrt(w @ cov @ w))
    met = ok and vol <= max_volatility + 1e-6
    status = "optimal"
    if not met:
        w, ok = solve(base)
        vol = float(np.sqrt(w @ cov @ w))
        met = vol <= max_volatility + 1e-6
        status = "volatility_limit_unreachable" if not met else "optimal"
    if not ok:
        status = "solver_warning"
    return WeightResult(
        weights={t: float(x) for t, x in zip(tickers, w, strict=True)},
        expected_return=float(w @ mu),
        volatility=vol,
        utility=float(w @ mu - risk_aversion * w @ cov @ w),
        volatility_limit_met=met,
        sector_weights={s: float(w[idx].sum()) for s, idx in sector_idx.items()},
        status=status,
    )
