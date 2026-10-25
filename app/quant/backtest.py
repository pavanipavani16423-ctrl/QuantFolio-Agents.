"""Out-of-sample backtest: buy at the first close after the estimation window, then hold.

Every portfolio is estimated on [train_start, train_end] and evaluated on the days after
train_end, which the optimizer never saw. Buy-and-hold (no rebalancing, no costs) keeps the
comparison simple and identical for every method.
"""

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _metrics(values: pd.Series, risk_free: float) -> dict:
    daily = values.pct_change().dropna()
    years = len(daily) / TRADING_DAYS
    total = float(values.iloc[-1] / values.iloc[0] - 1)
    ann_ret = float((1 + total) ** (1 / years) - 1) if years > 0 else 0.0
    ann_vol = float(daily.std(ddof=1) * np.sqrt(TRADING_DAYS))
    peak = values.cummax()
    return {
        "total_return": total,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": (ann_ret - risk_free) / ann_vol if ann_vol > 0 else None,
        "max_drawdown": float((1 - values / peak).max()),
    }


def backtest(portfolios: dict[str, dict[str, float]], prices: pd.DataFrame, start_after: str,
             risk_free: float = 0.04, end: str | None = None) -> dict:
    """`portfolios`: name -> {ticker: weight}. Returns metrics and equity curves (start = 100)."""
    window = prices.loc[prices.index > pd.Timestamp(start_after)]
    if end:
        window = window.loc[:end]
    if len(window) < 20:
        raise ValueError("fewer than 20 out-of-sample days after the estimation window")
    results, curves = {}, {}
    for name, weights in portfolios.items():
        w = pd.Series({t: v for t, v in weights.items() if v > 0}, dtype=float)
        w = w / w.sum()
        growth = window[w.index] / window[w.index].iloc[0]
        values = 100 * (growth * w).sum(axis=1)
        results[name] = _metrics(values, risk_free)
        curves[name] = [round(float(v), 3) for v in values]
    return {
        "start": str(window.index[0].date()),
        "end": str(window.index[-1].date()),
        "days": int(len(window)),
        "method": "buy-and-hold from the first close after the estimation window, no costs",
        "risk_free_rate": risk_free,
        "metrics": results,
        "dates": [str(d.date()) for d in window.index],
        "curves": curves,
    }
