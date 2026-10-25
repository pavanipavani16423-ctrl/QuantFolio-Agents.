"""Split documents into retrieval chunks.

Every chunk carries a short contextual header ("Apple Inc. (AAPL) 10-K risk factors: ...")
that is indexed together with the chunk text, so a paragraph that never names its company
can still be found by a query that does.
"""

import re
from dataclasses import asdict, dataclass

from app.data.store import Document

TARGET_CHARS = 1100
MAX_CHARS = 1600

DOC_TYPE_LABEL = {
    "risk_factors": "10-K Item 1A risk factors",
    "mdna": "10-K Item 7 management's discussion and analysis",
    "facts": "financial facts (SEC XBRL)",
    "mandate": "investment policy statement",
    "ar_mdna": "annual report management discussion and analysis (SEBI)",
    "ar_risk": "annual report risks and risk management",
    "brsr": "business responsibility and sustainability report (BRSR, SEBI)",
}


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    title: str
    section: str
    text: str
    header: str
    ticker: str | None = None
    client_id: str | None = None
    source_url: str | None = None
    market: str | None = None

    @property
    def index_text(self) -> str:
        return f"{self.header}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


def _header(doc: Document, section: str) -> str:
    parts = doc.title.split(" - ")
    # mandate titles read "Investment Policy Statement - <client> (client C-1xx) - <profile>"
    who = parts[1] if doc.doc_type == "mandate" and len(parts) > 1 else parts[0]
    label = DOC_TYPE_LABEL.get(doc.doc_type, doc.doc_type)
    return f"{who} {label}" + (f" - {section}" if section else "")


def _is_heading(line: str) -> bool:
    return 3 < len(line) < 120 and not line.endswith((".", ",", ";", ":")) and line[0].isupper()


def _pack(paragraphs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Greedy paragraph packing to ~TARGET_CHARS; overly long paragraphs are split on sentences."""
    pieces: list[tuple[str, str]] = []
    for section, para in paragraphs:
        if len(para) <= MAX_CHARS:
            pieces.append((section, para))
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        buf = ""
        for sentence in sentences:
            if buf and len(buf) + len(sentence) > TARGET_CHARS:
                pieces.append((section, buf.strip()))
                buf = ""
            buf += sentence + " "
        if buf.strip():
            pieces.append((section, buf.strip()))

    chunks: list[tuple[str, str]] = []
    section, buf = "", ""
    for sec, piece in pieces:
        if buf and (len(buf) + len(piece) > TARGET_CHARS or sec != section):
            chunks.append((section, buf.strip()))
            buf = ""
        if not buf:
            section = sec
        buf += piece + "\n\n"
    if buf.strip():
        chunks.append((section, buf.strip()))
    return chunks


def _chunk_filing(doc: Document) -> list[tuple[str, str]]:
    lines = doc.text.splitlines()
    body = [ln for ln in lines[1:] if not ln.startswith(("Source: SEC EDGAR", "(Excerpt:"))]
    paragraphs: list[tuple[str, str]] = []
    section = ""
    for line in (ln.strip() for ln in body):
        if not line:
            continue
        if _is_heading(line) and not re.match(r"item\s*\d", line, flags=re.I):
            section = line
            continue
        paragraphs.append((section, line))
    return _pack(paragraphs)


def _chunk_facts(doc: Document) -> list[tuple[str, str]]:
    groups: dict[str, list[str]] = {}
    for line in doc.text.splitlines():
        m = re.match(r"- .*? reported (.+?) of ", line)
        if m:
            groups.setdefault(m.group(1), []).append(line[2:])
    return [(label.capitalize(), "\n".join(rows)) for label, rows in groups.items()]


def _chunk_mandate(doc: Document) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for block in re.split(r"(?m)^## ", doc.text)[1:]:
        heading, _, body = block.partition("\n")
        out.append((heading.strip(), body.strip()))
    return out


def chunk_document(doc: Document) -> list[Chunk]:
    if doc.doc_type == "facts":
        parts = _chunk_facts(doc)
    elif doc.doc_type == "mandate":
        parts = _chunk_mandate(doc)
    else:
        parts = _chunk_filing(doc)
    return [
        Chunk(
            chunk_id=f"{doc.doc_id}#{i:03d}",
            doc_id=doc.doc_id,
            doc_type=doc.doc_type,
            title=doc.title,
            section=section,
            text=text,
            header=_header(doc, section),
            ticker=doc.ticker,
            client_id=doc.client_id,
            source_url=doc.source_url,
            market=doc.market,
        )
        for i, (section, text) in enumerate(parts)
        if len(text) > 40
    ]
