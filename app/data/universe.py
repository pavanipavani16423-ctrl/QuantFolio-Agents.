"""The investable universes, one per market.

* US: 20 large caps across 10 sectors (NYSE/Nasdaq, USD). Research uses SEC filings
  (10-K Item 1A risk factors, Item 7 MD&A, XBRL facts). Benchmark: SPY.
* India: 18 large caps across 10 sectors (NSE, INR). Research uses the documents Indian
  regulation requires instead: the annual report's Management Discussion and Analysis
  (SEBI LODR Regulation 34), its risk-management section, and the Business Responsibility
  and Sustainability Report (BRSR, SEBI), plus reported financials. Benchmark: Nifty 50.

The lists are fixed so every run, test and experiment sees the same assets. Benchmarks are
only used for comparison and are never bought.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    exchange: str
    currency: str
    symbol: str
    benchmark: str  # column name in the price file
    benchmark_name: str
    regulator: str
    risk_free_rate: float
    research_doc_types: tuple[str, ...]
    research_sources: str


MARKETS: dict[str, Market] = {
    "US": Market("US", "United States", "NYSE / Nasdaq", "USD", "$", "SPY", "S&P 500 (SPY)", "SEC",
                 0.04, ("risk_factors", "mdna"),
                 "SEC Form 10-K (Item 1A risk factors, Item 7 MD&A) and XBRL financial facts"),
    "IN": Market("IN", "India", "NSE", "INR", "₹", "NIFTY50", "Nifty 50", "SEBI",
                 0.065, ("ar_risk", "ar_mdna", "brsr"),
                 "Annual report (SEBI-mandated MD&A and risk management), BRSR sustainability "
                 "report and reported financials"),
}


@dataclass(frozen=True)
class Asset:
    ticker: str
    name: str
    sector: str
    cik: int = 0  # SEC id (US only)
    market: str = "US"

    @property
    def yahoo(self) -> str:
        return f"{self.ticker}.NS" if self.market == "IN" else self.ticker


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

UNIVERSE_IN: tuple[Asset, ...] = tuple(
    Asset(t, n, s, market="IN") for t, n, s in (
        ("RELIANCE", "Reliance Industries Limited", "Energy"),
        ("ONGC", "Oil and Natural Gas Corporation Limited", "Energy"),
        ("TCS", "Tata Consultancy Services Limited", "Information Technology"),
        ("INFY", "Infosys Limited", "Information Technology"),
        ("HDFCBANK", "HDFC Bank Limited", "Financials"),
        ("ICICIBANK", "ICICI Bank Limited", "Financials"),
        ("SBIN", "State Bank of India", "Financials"),
        ("BHARTIARTL", "Bharti Airtel Limited", "Communication Services"),
        ("HINDUNILVR", "Hindustan Unilever Limited", "Consumer Staples"),
        ("ITC", "ITC Limited", "Consumer Staples"),
        ("MARUTI", "Maruti Suzuki India Limited", "Consumer Discretionary"),
        ("TITAN", "Titan Company Limited", "Consumer Discretionary"),
        ("SUNPHARMA", "Sun Pharmaceutical Industries Limited", "Health Care"),
        ("LT", "Larsen & Toubro Limited", "Industrials"),
        ("NTPC", "NTPC Limited", "Utilities"),
        ("TATASTEEL", "Tata Steel Limited", "Materials"),
        ("ULTRACEMCO", "UltraTech Cement Limited", "Materials"),
        ("ASIANPAINT", "Asian Paints Limited", "Materials"),
    )
)

UNIVERSES: dict[str, tuple[Asset, ...]] = {"US": UNIVERSE, "IN": UNIVERSE_IN}
ALL_ASSETS: tuple[Asset, ...] = UNIVERSE + UNIVERSE_IN

# US aliases kept for the SEC data scripts
BENCHMARK = MARKETS["US"].benchmark
TICKERS: tuple[str, ...] = tuple(a.ticker for a in UNIVERSE)

BY_TICKER: dict[str, Asset] = {a.ticker: a for a in ALL_ASSETS}
SECTORS: tuple[str, ...] = tuple(sorted({a.sector for a in ALL_ASSETS}))


def universe(market: str) -> tuple[Asset, ...]:
    return UNIVERSES[market]


def tickers(market: str) -> list[str]:
    return [a.ticker for a in UNIVERSES[market]]


def market_of(ticker: str) -> str:
    return BY_TICKER[ticker].market


def market_of_tickers(symbols: list[str]) -> str:
    """The one market a list of tickers belongs to (benchmarks are allowed)."""
    benchmarks = {m.benchmark: m.code for m in MARKETS.values()}
    found = {BY_TICKER[t].market if t in BY_TICKER else benchmarks[t] for t in symbols}
    if len(found) != 1:
        raise ValueError(f"tickers from more than one market: {sorted(symbols)}")
    return found.pop()


def sector_of(ticker: str) -> str:
    return BY_TICKER[ticker].sector
