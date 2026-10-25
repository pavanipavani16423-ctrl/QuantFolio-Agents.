"""The investable universe: 20 US large caps across 10 GICS sectors, plus SPY as benchmark.

The list is fixed so every run, test and experiment sees the same assets. SPY is used only
as a benchmark (beta, backtest comparison) and is never bought by the optimizer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    ticker: str
    name: str
    sector: str
    cik: int


UNIVERSE: tuple[Asset, ...] = (
    Asset("AAPL", "Apple Inc.", "Information Technology", 320193),
    Asset("MSFT", "Microsoft Corporation", "Information Technology", 789019),
    Asset("NVDA", "NVIDIA Corporation", "Information Technology", 1045810),
    Asset("GOOGL", "Alphabet Inc.", "Communication Services", 1652044),
    Asset("META", "Meta Platforms, Inc.", "Communication Services", 1326801),
    Asset("AMZN", "Amazon.com, Inc.", "Consumer Discretionary", 1018724),
    Asset("HD", "The Home Depot, Inc.", "Consumer Discretionary", 354950),
    Asset("JPM", "JPMorgan Chase & Co.", "Financials", 19617),
    Asset("V", "Visa Inc.", "Financials", 1403161),
    Asset("JNJ", "Johnson & Johnson", "Health Care", 200406),
    Asset("UNH", "UnitedHealth Group Incorporated", "Health Care", 731766),
    Asset("PFE", "Pfizer Inc.", "Health Care", 78003),
    Asset("XOM", "Exxon Mobil Corporation", "Energy", 34088),
    Asset("CVX", "Chevron Corporation", "Energy", 93410),
    Asset("PG", "The Procter & Gamble Company", "Consumer Staples", 80424),
    Asset("KO", "The Coca-Cola Company", "Consumer Staples", 21344),
    Asset("WMT", "Walmart Inc.", "Consumer Staples", 104169),
    Asset("CAT", "Caterpillar Inc.", "Industrials", 18230),
    Asset("NEE", "NextEra Energy, Inc.", "Utilities", 753308),
    Asset("LIN", "Linde plc", "Materials", 1707925),
)

BENCHMARK = "SPY"

BY_TICKER: dict[str, Asset] = {a.ticker: a for a in UNIVERSE}
TICKERS: tuple[str, ...] = tuple(a.ticker for a in UNIVERSE)
SECTORS: tuple[str, ...] = tuple(sorted({a.sector for a in UNIVERSE}))


def sector_of(ticker: str) -> str:
    return BY_TICKER[ticker].sector
