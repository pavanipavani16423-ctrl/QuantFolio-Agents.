"""Download the India data snapshot (run once; the result is committed).

Indian companies do not file with the SEC, so research uses the documents Indian regulation
requires instead:

* prices: daily adjusted closes of 18 NSE large caps and the Nifty 50 (Yahoo Finance);
* financial facts: annual revenue, profit, EPS, assets, debt, cash (Yahoo Finance), in
  ₹ crore with Indian digit grouping;
* the latest annual report from NSE (www.nseindia.com/api/annual-reports), from which three
  sections are extracted:
  - Management Discussion and Analysis (required by SEBI LODR Regulation 34),
  - its risk-management / risks-and-concerns part,
  - the Business Responsibility and Sustainability Report (BRSR, SEBI): the table of
    material ESG risks and opportunities, and Principle 6 (environment).

    uv run python scripts/fetch_india.py [--only TCS INFY] [--skip-prices]
"""

import argparse
import json
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.universe import MARKETS, UNIVERSE_IN  # noqa: E402

DATA = ROOT / "data"
NSE = "https://www.nseindia.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0 Safari/537.36",
    "Accept": "application/json,application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
SECTION_LIMIT = 30_000


def inr_crore(value: float) -> str:
    """₹ amount in crore with Indian digit grouping: 2670210000000 -> ₹2,67,021 crore."""
    crore = value / 1e7
    sign = "-" if crore < 0 else ""
    whole = f"{abs(crore):.0f}"
    if len(whole) > 3:
        tail = whole[-3:]
        # the digits before the last three are grouped in pairs (lakh, crore, ...)
        head_digits = whole[:-3]
        groups = []
        while len(head_digits) > 2:
            groups.insert(0, head_digits[-2:])
            head_digits = head_digits[:-2]
        if head_digits:
            groups.insert(0, head_digits)
        whole = ",".join(groups) + "," + tail
    return f"{sign}₹{whole} crore"


def fetch_prices(start: str, end: str) -> None:
    import yfinance as yf

    symbols = [a.yahoo for a in UNIVERSE_IN] + ["^NSEI"]
    frame = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)["Close"]
    frame = frame[symbols].dropna(how="any")
    frame.columns = [a.ticker for a in UNIVERSE_IN] + [MARKETS["IN"].benchmark]
    frame.index = frame.index.strftime("%Y-%m-%d")
    frame.index.name = "date"
    frame.round(4).to_csv(DATA / "market" / "prices_in.csv")
    meta = {"source": "Yahoo Finance via yfinance (NSE, adjusted close; Nifty 50 = ^NSEI)",
            "symbols": list(frame.columns), "start": frame.index[0], "end": frame.index[-1],
            "rows": int(frame.shape[0]), "currency": "INR", "downloaded": date.today().isoformat()}
    (DATA / "market" / "prices_in.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"prices: {frame.shape[0]} days x {frame.shape[1]} symbols ({meta['start']} .. {meta['end']})")


FACT_ROWS = [  # (label, statement, row names in order of preference, per-share?)
    ("Total revenue", "income", ["Total Revenue", "Operating Revenue"], False),
    ("Operating income", "income", ["Operating Income", "EBIT"], False),
    ("Net income", "income", ["Net Income", "Net Income Common Stockholders"], False),
    ("Diluted earnings per share", "income", ["Diluted EPS", "Basic EPS"], True),
    ("Net cash from operating activities", "cash", ["Operating Cash Flow"], False),
    ("Total assets", "balance", ["Total Assets"], False),
    ("Total debt", "balance", ["Total Debt"], False),
    ("Cash and cash equivalents", "balance", ["Cash And Cash Equivalents", "Cash Financial"], False),
    ("Stockholders' equity", "balance", ["Stockholders Equity", "Common Stock Equity"], False),
]


def fetch_facts(asset) -> int:  # noqa: ANN001
    import pandas as pd
    import yfinance as yf

    tk = yf.Ticker(asset.yahoo)
    statements = {"income": tk.income_stmt, "balance": tk.balance_sheet, "cash": tk.cashflow}
    lines = [f"# {asset.name} ({asset.ticker}) - key financial facts", "",
             f"Sector: {asset.sector}. Listed on NSE (India). Source: annual financial statements "
             "via Yahoo Finance, amounts in Indian rupees (1 crore = 10 million).", ""]
    count = 0
    for label, kind, rows, per_share in FACT_ROWS:
        frame = statements[kind]
        row = next((r for r in rows if frame is not None and r in frame.index), None)
        if row is None:
            continue
        series = frame.loc[row].dropna().sort_index(ascending=False)[:3]
        if series.empty:
            continue
        count += 1
        for period, value in series.items():
            end = pd.Timestamp(period).date()
            amount = f"₹{value:,.2f}" if per_share else inr_crore(float(value))
            what = "as of" if kind == "balance" else "for the fiscal year ended"
            lines.append(f"- {asset.name} ({asset.ticker}) reported {label.lower()} of {amount} {what} "
                         f"{end} (fiscal year {end.year}; FY{end.year - 1}-{str(end.year)[2:]}; "
                         "annual financial statements via Yahoo Finance).")
    folder = DATA / "corpus" / "facts_in"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{asset.ticker}.md").write_text("\n".join(lines) + "\n", "utf-8")
    return count


# ---- annual report sections ------------------------------------------------------------------

def clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    out = []
    for ln in lines:
        if not ln or re.fullmatch(r"[\d\s|.-]{1,6}", ln):  # page numbers and rules
            continue
        out.append(ln)
    # re-join lines broken mid-sentence by the PDF layout
    joined, buf = [], ""
    for ln in out:
        buf = f"{buf} {ln}".strip() if buf else ln
        if re.search(r"[.:;!?)]$", ln) or len(ln) < 60:
            joined.append(buf)
            buf = ""
    if buf:
        joined.append(buf)
    return "\n".join(joined)


def longest_run(pages: list[str], pattern: str, min_page: int = 4, gap: int = 2) -> tuple[int, int] | None:
    hits = [i for i, p in enumerate(pages) if i >= min_page and re.search(pattern, p, re.I)]
    if not hits:
        return None
    runs, start, prev = [], hits[0], hits[0]
    for h in hits[1:]:
        if h - prev > gap:
            runs.append((start, prev))
            start = h
        prev = h
    runs.append((start, prev))
    return max(runs, key=lambda r: r[1] - r[0])


def section_text(pages: list[str], run: tuple[int, int] | None, extra: int = 1) -> str:
    if run is None:
        return ""
    return clean("\n".join(pages[run[0]: min(len(pages), run[1] + 1 + extra)]))


RISK_LINE = re.compile(r"\b(risks?|threats?|concerns?|challenges?|uncertaint\w*|headwinds?|mitigat\w*)\b", re.I)


def risk_paragraphs(text: str, limit: int) -> str:
    """Paragraphs that talk about risks, each with the paragraph that follows it."""
    paras = [p for p in text.split("\n") if len(p) > 40]
    keep: list[int] = []
    for i, p in enumerate(paras):
        if RISK_LINE.search(p) and not re.search(r"\d[\d,.]*\s*%.*\d[\d,.]*\s*%.*\d", p):  # skip number tables
            keep += [i, i + 1]
    out, seen = [], set()
    for i in keep:
        if i < len(paras) and i not in seen:
            seen.add(i)
            out.append(paras[i])
    return "\n".join(out)[:limit]


def extract_sections(pages: list[str]) -> dict[str, str]:
    # Narrative part only: stop where the audited financial statements begin, i.e. the first
    # page whose top reads "Independent Auditor's Report" (contents pages only mention it).
    fin_start = next((i for i, p in enumerate(pages)
                      if i >= 10 and re.search(r"independent\s+auditor.?s\s+report", p[:300], re.I)
                      and not re.search(r"contents|index", p[:300], re.I)), len(pages))
    narrative = pages[:fin_start]
    mdna = section_text(narrative, longest_run(narrative, r"management.?s?\s+discussion\s*(?:&|and)\s*analysis"))
    risk = risk_paragraphs(mdna, SECTION_LIMIT)
    if len(risk) < 3000:  # little risk text in the MD&A: use the board's risk-management pages
        board = section_text(narrative, longest_run(narrative, r"risk\s+management|risks?\s+(?:and|&)\s+(?:concerns|mitigation)"))
        risk = (risk + "\n" + risk_paragraphs(board, SECTION_LIMIT)).strip()
    brsr_all = section_text(narrative, longest_run(narrative, r"business\s+responsibility\s*(?:&|and)\s*sustainability"), extra=0)
    if not brsr_all:  # some companies attach the BRSR after the financial statements
        brsr_all = section_text(pages, longest_run(pages, r"business\s+responsibility\s*(?:&|and)\s*sustainability"), extra=0)
    parts = []
    for pattern in (r"material responsible business conduct", r"principle\s*6\b"):
        hit = re.search(pattern, brsr_all, re.I)
        if hit:
            parts.append(brsr_all[hit.start(): hit.start() + SECTION_LIMIT // 2])
    brsr = "\n\n".join(parts) if parts else brsr_all[:SECTION_LIMIT]
    return {"ar_mdna": mdna[:SECTION_LIMIT], "ar_risk": risk[:SECTION_LIMIT], "brsr": brsr[:SECTION_LIMIT]}


TITLES = {
    "ar_mdna": "Annual Report - Management Discussion and Analysis (SEBI LODR Reg. 34)",
    "ar_risk": "Annual Report - Risk management and risks and concerns",
    "brsr": "Business Responsibility and Sustainability Report (BRSR, SEBI)",
}


def fetch_annual_report(client: httpx.Client, asset, tmp: Path) -> dict:  # noqa: ANN001
    from pypdf import PdfReader

    reports = client.get(f"{NSE}/annual-reports", params={"index": "equities", "symbol": asset.ticker}).json()["data"]
    last_error: Exception | None = None
    for report in reports[:3]:  # newest first; fall back if a file is damaged
        url = report["fileName"]
        pdf = tmp / f"{asset.ticker}_{report['fromYr']}_{report['toYr']}.pdf"
        for attempt in range(4):  # NSE sometimes drops large downloads
            if pdf.exists() and pdf.stat().st_size > 100_000:
                break
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with pdf.open("wb") as fh:
                        for chunk in response.iter_bytes(1 << 20):
                            fh.write(chunk)
            except httpx.HTTPError:
                pdf.unlink(missing_ok=True)
                time.sleep(3 * (attempt + 1))
        try:
            reader = PdfReader(str(pdf))
            _ = len(reader.pages)
            break
        except Exception as exc:  # noqa: BLE001 - damaged or non-PDF file: try the previous year
            last_error = exc
            pdf.unlink(missing_ok=True)
    else:
        raise RuntimeError(f"no readable annual report: {last_error}")
    started = time.perf_counter()
    pages = []
    for page in reader.pages:  # one unreadable page must not lose the whole report
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - pypdf limits on pathological content streams
            pages.append("")
    sections = extract_sections(pages)
    period = f"{report['fromYr']}-{report['toYr']}"
    folder = DATA / "corpus" / "filings_in"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"ticker": asset.ticker, "name": asset.name, "period": period, "url": url,
            "pages": len(pages), "parse_seconds": round(time.perf_counter() - started, 1), "sections": {}}
    for key, body in sections.items():
        if len(body) < 1500:
            meta["sections"][key] = {"chars": len(body), "skipped": True}
            continue
        header = (f"# {asset.name} ({asset.ticker}) - {TITLES[key]} - FY {period}\n\n"
                  f"Source: NSE annual report filing, {url}\n\n")
        (folder / f"{asset.ticker}_{key}.md").write_text(header + body + "\n", "utf-8")
        meta["sections"][key] = {"chars": len(body)}
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-10-24")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if not args.skip_prices:
        fetch_prices(args.start, args.end)
    manifest_path = DATA / "corpus" / "filings_in" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    # downloaded PDFs (5-40 MB each) are cached outside the repo between runs
    tmp = Path(tempfile.gettempdir()) / "quantfolio-nse-reports"
    tmp.mkdir(exist_ok=True)
    with httpx.Client(headers=HEADERS, timeout=180, follow_redirects=True) as client:
        for asset in UNIVERSE_IN:
            if args.only and asset.ticker not in args.only:
                continue
            facts = fetch_facts(asset)
            line = f"{asset.ticker}: {facts} fact rows"
            if not args.skip_reports:
                try:
                    meta = fetch_annual_report(client, asset, Path(tmp))
                    manifest[asset.ticker] = meta
                    line += f"; AR {meta['period']} {meta['pages']}p " + " ".join(
                        f"{k}={v['chars']}" for k, v in meta["sections"].items())
                except Exception as exc:  # noqa: BLE001 - report and continue
                    line += f"; annual report failed: {type(exc).__name__}: {exc}"
                time.sleep(1.0)
            print(line, flush=True)
            manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
