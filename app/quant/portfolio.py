"""Portfolio construction in two steps, shared by every method so they are compared fairly.

Step 1 - asset selection (the combinatorial part, where QAOA is applied):
    choose exactly k of the n allowed stocks to maximize the equal-weight mean-variance utility

        U(S) = (1/k) sum_{i in S} mu_i - lambda (1/k^2) sum_{i,j in S} Sigma_ij

    As a QUBO over x in {0,1}^n (minimize):

        E(x) = sum_i (-mu_i/k + lambda Sigma_ii/k^2) x_i + sum_{i<j} (2 lambda Sigma_ij/k^2) x_i x_j
               + A (sum_i x_i - k)^2

    The penalty A enforces the cardinality for the standard X-mixer QAOA; the XY-mixer QAOA
    preserves the number of selected assets by construction, so the penalty is zero there.
    A selection is feasible when it has exactly k assets and respects the per-sector name
    limit floor(max_sector_weight * k).

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

from app.quantum.qubo import QUBO

EXACT_LIMIT = 500_000  # max subsets for exhaustive search (C(20,10) = 184,756)


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

    def penalty(self) -> float:
        k2 = self.k**2
        lin = np.abs(-self.mu / self.k + self.risk_aversion * np.diag(self.cov) / k2)
        quad = np.abs(2 * self.risk_aversion * self.cov / k2)
        np.fill_diagonal(quad, 0)
        # larger than any single-variable gain, so adding/removing an asset never pays
        return float(2 * (lin.max() + quad.sum(axis=1).max()))

    def qubo(self, with_penalty: bool = True) -> QUBO:
        n, k, lam = self.n, self.k, self.risk_aversion
        linear = -self.mu / k + lam * np.diag(self.cov) / k**2
        quadratic = {
            (i, j): 2 * lam * self.cov[i, j] / k**2 for i in range(n) for j in range(i + 1, n)
        }
        offset = 0.0
        if with_penalty:
            a = self.penalty()
            linear = linear + a * (1 - 2 * k)
            for key in quadratic:
                quadratic[key] += 2 * a
            offset = a * k**2
        return QUBO(linear=linear, quadratic=quadratic, offset=offset, labels=list(self.tickers))


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
    energy: float
    feasible: bool
    seconds: float
    details: dict

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "selected": self.selected,
            "bitstring": "".join(str(int(b)) for b in self.bits),
            "utility": self.utility,
            "energy": self.energy,
            "feasible": self.feasible,
            "seconds": round(self.seconds, 4),
            "details": self.details,
        }


def _result(problem: SelectionProblem, method: str, bits: np.ndarray, started: float,
            details: dict) -> SelectionResult:
    qubo = problem.qubo(with_penalty=False)
    return SelectionResult(
        method=method,
        selected=[problem.tickers[i] for i in np.flatnonzero(bits)],
        bits=np.asarray(bits, dtype=np.int8),
        utility=problem.utility(bits),
        energy=qubo.energy(bits),
        feasible=problem.feasible(bits),
        seconds=time.perf_counter() - started,
        details=details,
    )


def select_exact(problem: SelectionProblem) -> SelectionResult:
    """Exhaustive search over all k-subsets: the proven optimum of the selection QUBO."""
    started = time.perf_counter()
    total = math.comb(problem.n, problem.k)
    if total > EXACT_LIMIT:
        raise ValueError(f"{total} subsets is too many for exhaustive search")
    combos = np.array(list(itertools.combinations(range(problem.n), problem.k)), dtype=np.int16)
    X = np.zeros((len(combos), problem.n), dtype=np.int8)
    np.put_along_axis(X, combos.astype(np.int64), 1, axis=1)
    qubo = problem.qubo(with_penalty=False)
    upper = np.zeros((problem.n, problem.n))
    for (i, j), v in qubo.quadratic.items():
        upper[i, j] = v
    Xf = X.astype(float)
    energies = qubo.offset + Xf @ qubo.linear + np.einsum("ij,ij->i", Xf @ upper, Xf)
    names = sorted(set(problem.sectors))
    onehot = np.array([[s == name for name in names] for s in problem.sectors], dtype=float)
    feasible = (Xf @ onehot).max(axis=1) <= problem.max_sector_names
    energies = np.where(feasible, energies, np.inf)
    order = np.argsort(energies)
    best = X[order[0]]
    return _result(problem, "classical_exact", best, started, {
        "subsets_evaluated": int(total),
        "feasible_subsets": int(feasible.sum()),
        "optimality": "proven (exhaustive search)",
        "worst_feasible_energy": float(energies[feasible].max()),
        "runner_up_energy": float(energies[order[1]]) if len(order) > 1 else None,
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
    return _result(problem, "greedy", bits, started, {"rule": "top-k by mu/sigma"})


def local_search(problem: SelectionProblem, bits: np.ndarray, max_rounds: int = 50) -> tuple[np.ndarray, int]:
    """Best-improvement 1-swap search (swap one held asset for one not held)."""
    qubo = problem.qubo(with_penalty=False)
    current = np.asarray(bits, dtype=np.int8).copy()
    current_e = qubo.energy(current) if problem.feasible(current) else np.inf
    moves = 0
    for _ in range(max_rounds):
        best_e, best_x = current_e, None
        for i in np.flatnonzero(current == 1):
            for j in np.flatnonzero(current == 0):
                cand = current.copy()
                cand[i], cand[j] = 0, 1
                if not problem.feasible(cand):
                    continue
                e = qubo.energy(cand)
                if e < best_e - 1e-12:
                    best_e, best_x = e, cand
        if best_x is None:
            break
        current, current_e = best_x, best_e
        moves += 1
    return current, moves


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
