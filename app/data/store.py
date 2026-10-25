"""Read-only access to the committed data snapshot (prices, documents, client accounts)."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.data.universe import BY_TICKER, MARKETS, tickers

PRICE_FILES = {"US": "prices", "IN": "prices_in"}


@dataclass(frozen=True)
class Document:
    doc_id: str  # e.g. "AAPL_risk_factors", "TCS_brsr", "AAPL_facts", "mandate_C-102"
    doc_type: str  # risk_factors | mdna | ar_mdna | ar_risk | brsr | facts | mandate
    title: str
    text: str
    ticker: str | None = None
    client_id: str | None = None
    source_url: str | None = None
    market: str | None = None


def data_dir() -> Path:
    return Path(get_settings().data_dir)


@lru_cache
def prices(market: str = "US") -> pd.DataFrame:
    frame = pd.read_csv(data_dir() / "market" / f"{PRICE_FILES[market]}.csv", index_col="date")
    frame.index = pd.to_datetime(frame.index)
    return frame[[*tickers(market), MARKETS[market].benchmark]].astype(float)


@lru_cache
def prices_meta(market: str = "US") -> dict:
    return json.loads((data_dir() / "market" / f"{PRICE_FILES[market]}.meta.json").read_text())


@lru_cache
def accounts() -> dict[str, dict]:
    raw = json.loads((data_dir() / "accounts.json").read_text())["accounts"]
    return {cid: {"market": "US", **acc} for cid, acc in raw.items()}


def account(client_id: str) -> dict:
    try:
        return accounts()[client_id]
    except KeyError:
        raise KeyError(f"unknown client {client_id!r}") from None


def market_of_client(client_id: str) -> str:
    return account(client_id)["market"]


@lru_cache
def filings_manifest(folder: str = "filings") -> dict:
    path = data_dir() / "corpus" / folder / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _title(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return first.lstrip("# ").strip()


@lru_cache
def documents() -> tuple[Document, ...]:
    root = data_dir() / "corpus"
    docs: list[Document] = []
    for folder in ("filings", "filings_in"):
        manifest = filings_manifest(folder)
        for path in sorted((root / folder).glob("*.md")):
            ticker, kind = path.stem.split("_", 1)
            text = path.read_text("utf-8")
            docs.append(Document(
                doc_id=path.stem, doc_type=kind, title=_title(text), text=text, ticker=ticker,
                source_url=manifest.get(ticker, {}).get("url"), market=BY_TICKER[ticker].market,
            ))
    for folder in ("facts", "facts_in"):
        for path in sorted((root / folder).glob("*.md")):
            text = path.read_text("utf-8")
            cik = re.search(r"CIK (\d+)", text)
            if cik:
                url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik.group(1)):010d}.json"
            else:
                url = f"https://finance.yahoo.com/quote/{BY_TICKER[path.stem].yahoo}/financials"
            docs.append(Document(
                doc_id=f"{path.stem}_facts", doc_type="facts", title=_title(text), text=text,
                ticker=path.stem, source_url=url, market=BY_TICKER[path.stem].market,
            ))
    for path in sorted((root / "mandates").glob("*.md")):
        text = path.read_text("utf-8")
        docs.append(Document(
            doc_id=f"mandate_{path.stem}", doc_type="mandate", title=_title(text), text=text,
            client_id=path.stem, market=accounts().get(path.stem, {}).get("market"),
        ))
    return tuple(docs)


def document(doc_id: str) -> Document:
    for doc in documents():
        if doc.doc_id == doc_id:
            return doc
    raise KeyError(f"unknown document {doc_id!r}")


def company_name(ticker: str) -> str:
    return BY_TICKER[ticker].name
