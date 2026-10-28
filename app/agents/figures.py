"""Key numbers for the research report, computed in code from the facts documents.

The model never writes these: revenue, operating income and net income come straight from the
SEC XBRL facts (US) or the reported financial statements (India), and growth and margin are
computed from them, each with its fiscal year and source document.
"""

import re
from typing import Any

from app.data import store

LINE = re.compile(r"reported (?P<label>[a-z ]+?) of (?P<value>[$₹][\d.,]+(?: (?:billion|million|crore|lakh))?) "
                  r"for the fiscal year ended (?P<end>\d{4}-\d{2}-\d{2}) \(fiscal year (?P<fy>\d{4})")
UNIT = {"billion": 1e9, "million": 1e6, "crore": 1e7, "lakh": 1e5}
LABELS = {"total revenue": "Revenue", "operating income": "Operating income", "net income": "Net income"}


def _amount(text: str) -> float:
    number, _, unit = text[1:].partition(" ")
    return float(number.replace(",", "")) * UNIT.get(unit, 1.0)


def key_figures(ticker: str) -> dict[str, Any] | None:
    try:
        doc = store.document(f"{ticker}_facts")
    except KeyError:
        return None
    rows: dict[str, dict[int, dict]] = {}
    for m in LINE.finditer(doc.text):
        label = m.group("label").strip()
        if label in LABELS:
            rows.setdefault(label, {})[int(m.group("fy"))] = {"value": m.group("value"), "end": m.group("end")}
    revenue = rows.get("total revenue")
    if not revenue:
        return None
    fy = max(revenue)
    items = []
    for key, label in LABELS.items():
        point = rows.get(key, {}).get(fy)
        if point:
            items.append({"label": label, "value": point["value"]})
    previous = revenue.get(fy - 1)
    if previous:
        growth = _amount(revenue[fy]["value"]) / _amount(previous["value"]) - 1
        items.append({"label": "Revenue growth", "value": f"{growth:+.1%}", "note": f"vs fiscal year {fy - 1}"})
    op = rows.get("operating income", {}).get(fy)
    if op:
        items.append({"label": "Operating margin", "value": f"{_amount(op['value']) / _amount(revenue[fy]['value']):.1%}"})
    return {"ticker": ticker, "company": store.company_name(ticker), "fiscal_year": fy,
            "period_end": revenue[fy]["end"], "items": items, "source": doc.title,
            "source_url": doc.source_url}
