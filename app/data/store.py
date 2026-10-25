"""Read-only access to the committed data snapshot (prices, documents, client accounts)."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.data.universe import BENCHMARK, BY_TICKER, TICKERS


@dataclass(frozen=True)
class Document:
    doc_id: str  # e.g. "AAPL_risk_factors", "AAPL_facts", "mandate_C-102"
    doc_type: str  # risk_factors | mdna | facts | mandate
    title: str
    text: str
    ticker: str | None = None
    client_id: str | None = None
    source_url: str | None = None


def data_dir() -> Path:
    return Path(get_settings().data_dir)


@lru_cache
def prices() -> pd.DataFrame:
    frame = pd.read_csv(data_dir() / "market" / "prices.csv", index_col="date")
    frame.index = pd.to_datetime(frame.index)
    return frame[[*TICKERS, BENCHMARK]].astype(float)


@lru_cache
def prices_meta() -> dict:
    return json.loads((data_dir() / "market" / "prices.meta.json").read_text())


@lru_cache
def accounts() -> dict[str, dict]:
    return json.loads((data_dir() / "accounts.json").read_text())["accounts"]


def account(client_id: str) -> dict:
    try:
        return accounts()[client_id]
    except KeyError:
        raise KeyError(f"unknown client {client_id!r}") from None


@lru_cache
def filings_manifest() -> dict:
    path = data_dir() / "corpus" / "filings" / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _title(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return first.lstrip("# ").strip()


@lru_cache
def documents() -> tuple[Document, ...]:
    root = data_dir() / "corpus"
    manifest = filings_manifest()
    docs: list[Document] = []
    for path in sorted((root / "filings").glob("*.md")):
        ticker, kind = path.stem.split("_", 1)
        text = path.read_text("utf-8")
        docs.append(Document(
            doc_id=path.stem, doc_type=kind, title=_title(text), text=text, ticker=ticker,
            source_url=manifest.get(ticker, {}).get("url"),
        ))
    for path in sorted((root / "facts").glob("*.md")):
        text = path.read_text("utf-8")
        cik = re.search(r"CIK (\d+)", text)
        docs.append(Document(
            doc_id=f"{path.stem}_facts", doc_type="facts", title=_title(text), text=text,
            ticker=path.stem,
            source_url=(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik.group(1)):010d}.json"
                if cik else None
            ),
        ))
    for path in sorted((root / "mandates").glob("*.md")):
        text = path.read_text("utf-8")
        docs.append(Document(
            doc_id=f"mandate_{path.stem}", doc_type="mandate", title=_title(text), text=text,
            client_id=path.stem,
        ))
    return tuple(docs)


def document(doc_id: str) -> Document:
    for doc in documents():
        if doc.doc_id == doc_id:
            return doc
    raise KeyError(f"unknown document {doc_id!r}")


def company_name(ticker: str) -> str:
    return BY_TICKER[ticker].name
