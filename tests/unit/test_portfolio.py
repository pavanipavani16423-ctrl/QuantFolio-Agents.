import numpy as np
import pandas as pd
import pytest

from app.quant.backtest import backtest
from app.quant.portfolio import local_search, optimize_weights, select_exact, selection_problem
from app.quant.stats import ledoit_wolf


def test_weights_respect_bounds_and_sector_caps() -> None:
    rng = np.random.default_rng(1)
    n = 6
    a = rng.normal(size=(n, n))
    cov = a @ a.T * 0.01 + np.eye(n) * 0.02
    mu = np.array([0.30, 0.25, 0.05, 0.04, 0.03, 0.02])
    sectors = ["Tech", "Tech", "Food", "Food", "Util", "Util"]
    w = optimize_weights([f"T{i}" for i in range(n)], sectors, mu, cov, 2.0, 0.05, 0.30, 0.40, 0.9)
    values = np.array(list(w.weights.values()))
    assert values.sum() == pytest.approx(1.0)
    assert values.min() >= 0.05 - 1e-6 and values.max() <= 0.30 + 1e-6
    assert w.sector_weights["Tech"] <= 0.40 + 1e-6


def test_infeasible_weight_bounds_are_rejected() -> None:
    with pytest.raises(ValueError):
        optimize_weights(["A", "B"], ["S", "S"], [0.1, 0.1], np.eye(2), 1.0, 0.6, 0.9, 1.0, 1.0)


def test_unreachable_volatility_limit_is_flagged() -> None:
    w = optimize_weights(["A", "B"], ["S", "R"], [0.1, 0.1], np.eye(2) * 0.25, 1.0, 0.1, 0.9, 1.0, 0.05)
    assert not w.volatility_limit_met
    assert w.status == "volatility_limit_unreachable"


def test_local_search_reaches_the_exact_optimum_on_a_small_problem() -> None:
    rng = np.random.default_rng(2)
    n, k = 10, 4
    a = rng.normal(size=(n, n))
    sp = selection_problem([f"T{i}" for i in range(n)], [f"S{i}" for i in range(n)],
                           rng.uniform(0, 0.3, n), a @ a.T * 0.01, k, 3.0, 1.0)
    start = np.zeros(n, dtype=np.int8)
    start[:k] = 1
    refined, _ = local_search(sp, start)
    assert sp.utility(refined) >= sp.utility(start)
    assert sp.utility(refined) <= select_exact(sp).utility + 1e-12


def test_ledoit_wolf_is_symmetric_positive_definite() -> None:
    returns = np.random.default_rng(0).normal(0, 0.01, size=(60, 20))  # fewer days than 3x assets
    cov, delta = ledoit_wolf(returns)
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > 0
    assert 0 <= delta <= 1


def test_backtest_buy_and_hold_metrics() -> None:
    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    prices = pd.DataFrame({"A": np.linspace(100, 120, 40), "B": np.full(40, 50.0)}, index=dates)
    result = backtest({"half": {"A": 0.5, "B": 0.5}}, prices, start_after="2025-12-31", risk_free=0.0)
    assert result["days"] == 40
    assert result["curves"]["half"][0] == pytest.approx(100.0)
    assert result["metrics"]["half"]["total_return"] == pytest.approx(0.10, abs=1e-6)
    assert result["metrics"]["half"]["max_drawdown"] == pytest.approx(0.0, abs=1e-9)
