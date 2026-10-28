"""Scope policy for requests: what this investment team will and will not do.

Blocked on purpose (an advisor tool must refuse these, whatever the wording):
* market abuse: insider information, front-running, pump-and-dump, spoofing, manipulation;
* financial crime: laundering, hiding money, tax evasion, sanctions evasion;
* promises: requests to guarantee returns or present the portfolio as risk-free.

Out of scope (politely refused, no agents run): requests with nothing to do with the client's
portfolio or the companies it may hold.
"""

import re
from dataclasses import dataclass

PROHIBITED: tuple[tuple[str, str], ...] = (
    ("insider_trading", r"\b(insider\s+(info|information|tip|knowledge)|non[- ]public\s+information|material\s+non[- ]public|mnpi|"
                        r"before\s+(the\s+)?(results|earnings|announcement)\s+(are|is)\s+(public|announced|released)|leaked\s+(results|earnings))\b"),
    ("market_manipulation", r"\b(pump\s+(and|&)\s+dump|pump\s+up\s+the\s+price|spoof(ing)?|front[- ]?run(ning)?|wash\s+trad(e|ing)|"
                            r"manipulat(e|ing)\s+(the\s+)?(price|market|stock)|corner\s+the\s+market|circular\s+trading)\b"),
    ("financial_crime", r"\b(launder(ing)?|money\s+laundering|hide\s+(the\s+)?(money|funds|income)|evade\s+(tax|taxes)|tax\s+evasion|"
                        r"benami|hawala|avoid\s+(sanctions|kyc|aml)|bypass\s+(kyc|aml))\b"),
    ("guaranteed_returns", r"\b(guarantee[sd]?|promise)\b[^.\n]{0,40}\b(returns?|profits?|gains?|income|won'?t\s+lose)\b"
                           r"|\b(risk[- ]free|zero[- ]risk|can'?t\s+lose|no\s+chance\s+of\s+loss)\b[^.\n]{0,30}\b(returns?|portfolio|investment|profit)\b"),
)
_PROHIBITED = tuple((name, re.compile(p, re.I)) for name, p in PROHIBITED)

DOMAIN = re.compile(
    r"\b(portfolio|rebalanc\w*|invest\w*|stocks?|shares?|equit\w*|holdings?|positions?|risks?|returns?|"
    r"sectors?|allocat\w*|weights?|diversif\w*|volatil\w*|mandate|clients?|trust|endowment|foundation|"
    r"family|esg|climate|sustainab\w*|emissions?|brsr|annual\s+report|10-?k|filings?|disclos\w*|revenue|"
    r"earnings|profit|margin|debt|cash\s*flow|dividend|valuation|market|nifty|s&p|benchmark|compan(y|ies)|"
    r"business|supply|regulat\w*|tariffs?|currency|rupee|dollar|trades?|buy|sell|exposure|research)\b", re.I)


@dataclass
class ScopeResult:
    allowed: bool
    category: str  # ok | out_of_scope | <prohibited name>
    detail: str


# "we cannot promise returns", "do not guarantee anything": refusals, not requests
NEGATED = re.compile(r"\b(cannot|can'?t|do\s+not|don'?t|never|not|no|won'?t)\s+(promise|guarantee)\w*", re.I)


def check(text: str, market: str = "US") -> ScopeResult:
    for name, rx in _PROHIBITED:
        m = rx.search(NEGATED.sub(" ", text) if name == "guaranteed_returns" else text)
        if m:
            return ScopeResult(False, name, f"not allowed: {name.replace('_', ' ')} (\"{m.group(0)[:60]}\")")
    from app.agents.intake import mentioned_tickers  # tickers and company names, case-aware

    if not (DOMAIN.search(text) or mentioned_tickers(text, market)):
        return ScopeResult(False, "out_of_scope",
                           "the request is not about this client's portfolio or the companies it may hold")
    return ScopeResult(True, "ok", "about the client's portfolio and companies")
