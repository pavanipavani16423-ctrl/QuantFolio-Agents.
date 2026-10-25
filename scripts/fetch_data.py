"""Download the data snapshot the project runs on (run once; the result is committed).

* Daily adjusted close prices for the universe + SPY from Yahoo Finance (yfinance).
* For each company, from SEC EDGAR:
  - XBRL "company facts" -> a short facts document with the last three fiscal years;
  - the latest 10-K -> Item 1A (Risk Factors) and Item 7 (MD&A) as plain text.

SEC asks automated clients to identify themselves: set SEC_USER_AGENT to
"<your name or project> <contact email>". Requests are rate limited to ~5 per second.

    uv run python scripts/fetch_data.py [--start 2024-01-02] [--end 2026-10-23]
"""

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.universe import BENCHMARK, TICKERS, UNIVERSE  # noqa: E402

DATA = ROOT / "data"
USER_AGENT = os.environ.get("SEC_USER_AGENT", "QuantFolio-Agents academic research admin@example.com")
SECTION_CHAR_LIMIT = 40_000

# (label, unit, candidate us-gaap concepts in order of preference, kind)
FACTS = [
    ("Total revenue", "USD", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                               "RevenuesNetOfInterestExpense", "SalesRevenueNet"], "flow"),
    ("Operating income", "USD", ["OperatingIncomeLoss"], "flow"),
    ("Net income", "USD", ["NetIncomeLoss", "ProfitLoss"], "flow"),
    ("Diluted earnings per share", "USD/shares", ["EarningsPerShareDiluted"], "flow"),
    ("Research and development expense", "USD", ["ResearchAndDevelopmentExpense"], "flow"),
    ("Net cash from operating activities", "USD",
     ["NetCashProvidedByUsedInOperatingActivities"], "flow"),
    ("Total assets", "USD", ["Assets"], "stock"),
    ("Total liabilities", "USD", ["Liabilities"], "stock"),
    ("Cash and cash equivalents", "USD", ["CashAndCashEquivalentsAtCarryingValue"], "stock"),
    ("Long-term debt", "USD", ["LongTermDebtNoncurrent", "LongTermDebt"], "stock"),
    ("Stockholders' equity", "USD", ["StockholdersEquity"], "stock"),
]


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0  # depth inside a hidden element (script, style, display:none, ix:header)

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in self.VOID:
            if tag == "br" and not self.skip:
                self.parts.append("\n")
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if self.skip or tag in ("script", "style", "ix:header") or "display:none" in style:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001
        if tag == "br" and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in self.VOID:
            return
        if self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):  # noqa: ANN001
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    parser = _Text()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts)).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    out, blank = [], 0
    for ln in lines:
        # drop page furniture: bare page numbers and table-of-contents links
        if re.fullmatch(r"\d{1,3}|table of contents", ln, flags=re.I) or re.search(
            r"\|\s*\d{4} Form 10-K\s*\|\s*\d+$", ln
        ):
            continue
        if not ln:
            blank += 1
            if blank == 1:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def extract_section(text: str, start: str, ends: list[str]) -> str:
    """The longest span from a heading matching `start` to the next heading matching `ends`.

    10-Ks mention each item at least twice (table of contents, then the real section). In the
    table of contents the next item follows immediately, so the real section is the longest span.
    """
    end_re = re.compile("|".join(ends), flags=re.I | re.M)
    best = ""
    for m in re.finditer(start, text, flags=re.I | re.M):
        e = end_re.search(text, m.end())
        stop = e.start() if e else len(text)
        if stop - m.start() > len(best):
            best = text[m.start():stop]
    return best.strip()


MIN_SECTION_CHARS = 3000


def extract_items(text: str) -> dict[str, str]:
    risk = extract_section(
        text, r"^\s*item\s*1a\.?\s*[-:]?\s*risk\s+factors",
        [r"^\s*item\s*1b\.?", r"^\s*item\s*1c\.?", r"^\s*item\s*2\.?\s*[-:]?\s*properties"],
    )
    mdna_ends = [r"^\s*item\s*7a\.?", r"^\s*item\s*8\.?",
                 r"^\s*quantitative\s+and\s+qualitative\s+disclosures?\s+about\s+market\s+risk",
                 r"^\s*report\s+of\s+independent\s+registered"]
    mdna = extract_section(text, r"^\s*item\s*7\.?\s*[-:]?\s*management.s\s+discussion", mdna_ends)
    if len(mdna) < MIN_SECTION_CHARS:
        # some filers (e.g. Chevron) put MD&A in the financial section without an "Item 7" heading
        mdna = extract_section(
            text, r"^\s*management.s\s+discussion\s+and\s+analysis\s+of\s+financial\s+condition",
            mdna_ends,
        )
    return {"risk_factors": risk, "mdna": mdna}


class SEC:
    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
            timeout=60, follow_redirects=True,
        )
        self.last = 0.0

    def get(self, url: str) -> httpx.Response:
        wait = 0.2 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        response = self.client.get(url)
        response.raise_for_status()
        return response


def fetch_prices(start: str, end: str) -> None:
    import yfinance as yf

    symbols = [*TICKERS, BENCHMARK]
    frame = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)["Close"]
    frame = frame[symbols].dropna(how="any")
    frame.index = frame.index.strftime("%Y-%m-%d")
    frame.index.name = "date"
    path = DATA / "market" / "prices.csv"
    frame.round(4).to_csv(path)
    meta = {
        "source": "Yahoo Finance via yfinance (adjusted close: splits and dividends)",
        "symbols": symbols,
        "start": frame.index[0],
        "end": frame.index[-1],
        "rows": int(frame.shape[0]),
        "downloaded": date.today().isoformat(),
    }
    (DATA / "market" / "prices.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"prices: {frame.shape[0]} days x {frame.shape[1]} symbols ({meta['start']} .. {meta['end']})")


def _money(value: float, unit: str) -> str:
    if unit == "USD/shares":
        return f"${value:,.2f}"
    for div, suffix in ((1e9, "billion"), (1e6, "million")):
        if abs(value) >= div:
            return f"${value / div:,.1f} {suffix}"
    return f"${value:,.0f}"


def annual_values(facts: dict, concepts: list[str], unit: str, kind: str) -> tuple[str, dict]:
    """{fiscal_year: fact} for 10-K annual values, from the candidate concept with the most
    recent data (companies switch concepts over time, e.g. Revenues ->
    RevenueFromContractWithCustomerExcludingAssessedTax)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    best: tuple[str, dict] = ("", {})
    for concept in concepts:
        rows = gaap.get(concept, {}).get("units", {}).get(unit, [])
        by_year: dict[int, dict] = {}
        for row in rows:
            if row.get("form") != "10-K" or row.get("fp") != "FY":
                continue
            if kind == "flow":
                if "start" not in row:
                    continue
                days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
                if not 350 <= days <= 380:
                    continue
            year = date.fromisoformat(row["end"]).year
            # keep the value reported for the period itself (latest filing wins)
            if year not in by_year or row["filed"] > by_year[year]["filed"]:
                by_year[year] = row
        if by_year and (not best[1] or max(by_year) > max(best[1])):
            best = (concept, by_year)
    return best


def latest_10k(sec: SEC, cik: int) -> tuple[int, dict] | None:
    subs = sec.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    recent = subs["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return cik, {k: recent[k][i] for k in ("accessionNumber", "primaryDocument",
                                                    "filingDate", "reportDate")}
    return None


def fetch_company(sec: SEC, asset, sec_cik: int) -> dict:  # noqa: ANN001
    # A company can move to a new registrant CIK (e.g. a new holding company) before that
    # registrant has filed its first 10-K: use the newest CIK that has one.
    found = latest_10k(sec, sec_cik) or latest_10k(sec, asset.cik)
    if found is None:
        raise SystemExit(f"no 10-K found for {asset.ticker}")
    cik, filing = found
    cik10 = f"{cik:010d}"
    facts = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json").json()
    lines = [
        f"# {asset.name} ({asset.ticker}) - key financial facts",
        "",
        f"Sector: {asset.sector}. Source: SEC EDGAR XBRL company facts (Form 10-K annual values), "
        f"CIK {cik}.",
        "",
    ]
    table: dict[str, dict[str, float]] = {}
    for label, unit, concepts, kind in FACTS:
        concept, by_year = annual_values(facts, concepts, unit, kind)
        if not by_year:
            continue
        years = sorted(by_year)[-3:]
        table[label] = {str(y): by_year[y]["val"] for y in years}
        for y in reversed(years):
            row = by_year[y]
            what = "for the fiscal year ended" if kind == "flow" else "as of"
            lines.append(
                f"- {asset.name} ({asset.ticker}) reported {label.lower()} of "
                f"{_money(row['val'], unit)} {what} {row['end']} (fiscal year {y}; "
                f"10-K filed {row['filed']}, accession {row['accn']}, concept us-gaap:{concept})."
            )
    (DATA / "corpus" / "facts" / f"{asset.ticker}.md").write_text("\n".join(lines) + "\n", "utf-8")

    accession, doc = filing["accessionNumber"], filing["primaryDocument"]
    filed, period = filing["filingDate"], filing["reportDate"]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}"
    body = sec.get(url).content
    try:
        raw = body.decode("utf-8")
    except UnicodeDecodeError:
        raw = body.decode("cp1252", errors="replace")
    text = html_to_text(raw)

    sections = extract_items(text)
    meta = {"ticker": asset.ticker, "name": asset.name, "cik": cik, "form": "10-K", "filed": filed,
            "period": period, "accession": accession, "url": url, "sections": {}}
    for key, body in sections.items():
        truncated = len(body) > SECTION_CHAR_LIMIT
        body = body[:SECTION_CHAR_LIMIT]
        if truncated:  # cut at a paragraph boundary
            body = body[: body.rfind("\n")]
        title = "Item 1A. Risk Factors" if key == "risk_factors" else "Item 7. MD&A"
        header = (
            f"# {asset.name} ({asset.ticker}) - Form 10-K for the period ended {period} - {title}\n\n"
            f"Source: SEC EDGAR, filed {filed}, accession {accession}. {url}\n"
            + ("(Excerpt: the first part of the section.)\n" if truncated else "")
            + "\n"
        )
        (DATA / "corpus" / "filings" / f"{asset.ticker}_{key}.md").write_text(header + body + "\n", "utf-8")
        meta["sections"][key] = {"chars": len(body), "truncated": truncated}
    print(f"{asset.ticker}: facts {len(table)} metrics; 10-K {filed} "
          f"risk {meta['sections']['risk_factors']['chars']} chars, "
          f"mdna {meta['sections']['mdna']['chars']} chars")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-10-24")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--only", nargs="*", help="tickers to (re)fetch from SEC")
    args = parser.parse_args()

    for sub in ("market", "corpus/facts", "corpus/filings"):
        (DATA / sub).mkdir(parents=True, exist_ok=True)
    if not args.skip_prices:
        fetch_prices(args.start, args.end)

    sec = SEC()
    tickers_json = sec.get("https://www.sec.gov/files/company_tickers.json").json()
    sec_ciks = {row["ticker"]: int(row["cik_str"]) for row in tickers_json.values()}
    manifest_path = DATA / "corpus" / "filings" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for asset in UNIVERSE:
        if args.only and asset.ticker not in args.only:
            continue
        manifest[asset.ticker] = fetch_company(sec, asset, sec_ciks.get(asset.ticker, asset.cik))
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
