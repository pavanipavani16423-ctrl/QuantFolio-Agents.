"""Intake agent: turns the user's request into a structured task."""

import re

from app.data import store
from app.data.universe import BY_TICKER, MARKETS, universe
from app.graph.context import RunContext
from app.schemas import IntakeResult

DEFAULT_QUESTIONS = {
    "Conservative Income": "What risks to stable earnings and cash flows do these companies disclose?",
    "ESG Growth": "What climate-related or environmental risks do these companies disclose?",
    "Balanced Growth": "What are the most important business risks these companies disclose?",
    "Growth with Values": "What business and sustainability risks do these companies report?",
}


def system_prompt(market: str) -> str:
    m = MARKETS[market]
    return (
        "You are the intake agent of an investment team. Extract the client id, whether the user "
        "wants a rebalanced portfolio, the tickers they mention, and ONE research question that can "
        f"be answered from the companies' disclosures ({m.research_sources}). Universe ({m.name}, "
        f"{m.exchange}): " + ", ".join(f"{a.ticker} ({a.name})" for a in universe(market))
    )


ALIASES = {
    "AAPL": ["Apple"], "MSFT": ["Microsoft"], "NVDA": ["NVIDIA", "Nvidia"],
    "GOOGL": ["Alphabet", "Google"], "META": ["Meta", "Facebook"], "AMZN": ["Amazon"],
    "HD": ["Home Depot"], "JPM": ["JPMorgan", "JP Morgan", "J.P. Morgan"], "V": ["Visa"],
    "JNJ": ["Johnson & Johnson", "J&J"], "UNH": ["UnitedHealth"], "PFE": ["Pfizer"],
    "XOM": ["Exxon", "ExxonMobil"], "CVX": ["Chevron"], "PG": ["Procter & Gamble", "P&G"],
    "KO": ["Coca-Cola", "Coke"], "WMT": ["Walmart"], "CAT": ["Caterpillar"],
    "NEE": ["NextEra"], "LIN": ["Linde"],
    # India (NSE)
    "RELIANCE": ["Reliance"], "ONGC": ["ONGC", "Oil and Natural Gas"],
    "TCS": ["Tata Consultancy", "TCS"], "INFY": ["Infosys"], "HDFCBANK": ["HDFC Bank", "HDFC"],
    "ICICIBANK": ["ICICI"], "SBIN": ["State Bank", "SBI"], "BHARTIARTL": ["Bharti Airtel", "Airtel"],
    "HINDUNILVR": ["Hindustan Unilever", "HUL"], "ITC": ["ITC"], "MARUTI": ["Maruti"],
    "TITAN": ["Titan"], "SUNPHARMA": ["Sun Pharma"], "LT": ["Larsen", "L&T"], "NTPC": ["NTPC"],
    "TATASTEEL": ["Tata Steel"], "ULTRACEMCO": ["UltraTech"], "ASIANPAINT": ["Asian Paints"],
}


def mentioned_tickers(text: str, market: str = "US") -> list[str]:
    found = []
    for asset in universe(market):
        # one-letter tickers (V) only count in upper case and as a whole word
        names = ALIASES.get(asset.ticker, [])
        if re.search(rf"(?<![A-Za-z]){re.escape(asset.ticker)}(?![A-Za-z])", text) and (
            len(asset.ticker) > 1 or re.search(r"\bV\b(?!\.)", text)
        # names are proper nouns: match case-sensitively and as whole words, so "reliance on"
        # or "titanium" do not count as Reliance or Titan
        ) or any(re.search(rf"\b{re.escape(n)}(?![A-Za-z])", text) for n in names):
            found.append(asset.ticker)
    return found


def heuristic_intake(request: str, client_id: str) -> IntakeResult:
    account = store.account(client_id)
    questions = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", request) if s.strip().endswith("?")]
    question = questions[0] if questions else DEFAULT_QUESTIONS.get(
        account["profile"], "What are the main risks these companies disclose?")
    wants = not re.search(r"\b(only research|just research|no (?:trades|rebalanc))", request, re.I)
    return IntakeResult(client_id=client_id, wants_rebalance=wants, research_question=question,
                        focus_tickers=mentioned_tickers(request, account["market"]))


async def run_intake(ctx: RunContext, request: str, client_id: str) -> tuple[IntakeResult, str]:
    account = store.account(client_id)
    user = (f"Selected client: {client_id} ({account['name']}, {account['profile']}). "
            f"Current holdings: {', '.join(account['positions'])}.\n\nRequest: {request}")
    result, method = await ctx.llm.structured("intake", IntakeResult, system_prompt(account["market"]), user,
                                              fallback=lambda: heuristic_intake(request, client_id))
    # the client picked in the UI wins; tickers must exist in the client's market
    result.client_id = client_id
    result.focus_tickers = [t.upper() for t in result.focus_tickers
                            if t.upper() in BY_TICKER and BY_TICKER[t.upper()].market == account["market"]]
    # a company the request names always counts, even if the model left it out
    for ticker in mentioned_tickers(request, account["market"]):
        if ticker not in result.focus_tickers:
            result.focus_tickers.append(ticker)
    if not result.research_question.strip():
        result.research_question = heuristic_intake(request, client_id).research_question
    return result, method


def research_focus(intake: IntakeResult, client_id: str) -> list[str]:
    """Tickers to research: those mentioned, else the client's current holdings."""
    if intake.focus_tickers:
        return intake.focus_tickers[:8]
    return list(store.account(client_id)["positions"])[:8]
