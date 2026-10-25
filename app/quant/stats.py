"""Return and risk statistics used by the risk agent and the optimizer.

Estimation choices (deliberately simple and standard):

* expected returns: annualized mean daily log return, shrunk 50% toward the cross-sectional
  average (sample means are very noisy; shrinkage is the usual remedy);
* covariance: Ledoit-Wolf (2004) shrinkage of the sample covariance toward a scaled identity;
* VaR / CVaR: historical, 1-day, 95%;
* beta: OLS slope against SPY daily returns.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MEAN_SHRINKAGE = 0.5


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1)).dropna(how="any")


def ledoit_wolf(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit & Wolf (2004) shrinkage toward mu*I. Returns (covariance, shrinkage intensity)."""
    t, n = returns.shape
    x = returns - returns.mean(axis=0)
    sample = x.T @ x / t
    mu = np.trace(sample) / n
    target = mu * np.eye(n)
    d2 = np.sum((sample - target) ** 2)
    b2_bar = sum(np.sum((np.outer(row, row) - sample) ** 2) for row in x) / t**2
    b2 = min(b2_bar, d2)
    delta = 0.0 if d2 == 0 else b2 / d2
    return delta * target + (1 - delta) * sample, float(delta)


@dataclass
class MarketStats:
    tickers: list[str]
    start: str
    end: str
    observations: int
    mu: np.ndarray  # annualized expected returns (shrunk)
    sample_mu: np.ndarray  # annualized sample means (for reference)
    cov: np.ndarray  # annualized covariance (Ledoit-Wolf)
    shrinkage: float
    vol: np.ndarray
    beta: np.ndarray
    var95: np.ndarray  # 1-day historical VaR as a positive loss fraction
    max_drawdown: np.ndarray

    def to_dict(self) -> dict:
        corr = self.cov / np.outer(self.vol, self.vol)
        return {
            "tickers": self.tickers,
            "window": {"start": self.start, "end": self.end, "observations": self.observations},
            "expected_return": dict(zip(self.tickers, np.round(self.mu, 6).tolist(), strict=True)),
            "sample_mean_return": dict(
                zip(self.tickers, np.round(self.sample_mu, 6).tolist(), strict=True)
            ),
            "volatility": dict(zip(self.tickers, np.round(self.vol, 6).tolist(), strict=True)),
            "beta": dict(zip(self.tickers, np.round(self.beta, 4).tolist(), strict=True)),
            "var95_1d": dict(zip(self.tickers, np.round(self.var95, 6).tolist(), strict=True)),
            "max_drawdown": dict(
                zip(self.tickers, np.round(self.max_drawdown, 6).tolist(), strict=True)
            ),
            "covariance": np.round(self.cov, 8).tolist(),
            "correlation": np.round(corr, 4).tolist(),
            "covariance_shrinkage": round(self.shrinkage, 4),
            "method": {
                "expected_return": f"annualized mean log return, {int(MEAN_SHRINKAGE * 100)}% "
                "shrinkage to the cross-sectional mean",
                "covariance": "Ledoit-Wolf (2004) shrinkage to scaled identity, annualized",
                "var": "historical 1-day 95%",
            },
        }


def max_drawdown(log_returns: np.ndarray) -> np.ndarray:
    wealth = np.exp(np.cumsum(log_returns, axis=0))
    peak = np.maximum.accumulate(wealth, axis=0)
    return np.max(1 - wealth / peak, axis=0)


def market_stats(prices: pd.DataFrame, tickers: list[str], benchmark: str,
                 start: str, end: str) -> MarketStats:
    window = prices.loc[start:end]
    rets = daily_returns(window[[*tickers, benchmark]])
    r = rets[tickers].to_numpy()
    m = rets[benchmark].to_numpy()
    sample_mu = r.mean(axis=0) * TRADING_DAYS
    mu = (1 - MEAN_SHRINKAGE) * sample_mu + MEAN_SHRINKAGE * sample_mu.mean()
    cov_d, delta = ledoit_wolf(r)
    cov = cov_d * TRADING_DAYS
    m_c = m - m.mean()
    beta = ((r - r.mean(axis=0)) * m_c[:, None]).sum(axis=0) / (m_c @ m_c)
    return MarketStats(
        tickers=list(tickers),
        start=str(rets.index[0].date()),
        end=str(rets.index[-1].date()),
        observations=int(r.shape[0]),
        mu=mu,
        sample_mu=sample_mu,
        cov=cov,
        shrinkage=delta,
        vol=np.sqrt(np.diag(cov)),
        beta=beta,
        var95=-np.quantile(r, 0.05, axis=0),
        max_drawdown=max_drawdown(r),
    )


def portfolio_risk(weights: dict[str, float], prices: pd.DataFrame, benchmark: str,
                   start: str, end: str) -> dict:
    tickers = [t for t, w in weights.items() if w > 0]
    w = np.array([weights[t] for t in tickers])
    stats = market_stats(prices, tickers, benchmark, start, end)
    rets = daily_returns(prices.loc[start:end, tickers])
    # portfolio daily simple return with daily rebalancing to w (an approximation)
    simple = np.expm1(rets.to_numpy()) @ w
    port_log = np.log1p(simple)
    var95 = -np.quantile(simple, 0.05)
    tail = simple[simple <= -var95]
    return {
        "expected_return": float(w @ stats.mu),
        "volatility": float(np.sqrt(w @ stats.cov @ w)),
        "beta": float(w @ stats.beta),
        "var95_1d": float(var95),
        "cvar95_1d": float(-tail.mean()) if tail.size else float(var95),
        "max_drawdown": float(max_drawdown(port_log[:, None])[0]),
        "largest_weight": float(w.max()),
        "holdings": len(tickers),
        "window": {"start": stats.start, "end": stats.end},
    }
