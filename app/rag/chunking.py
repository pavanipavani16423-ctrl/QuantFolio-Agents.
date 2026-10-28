"""Split documents into retrieval chunks.

Every chunk carries a short contextual header ("Apple Inc. (AAPL) 10-K risk factors: ...")
that is indexed together with the chunk text, so a paragraph that never names its company
can still be found by a query that does.

The Indian annual reports are text extracted from PDFs: lines break mid-sentence. They are
reflowed into sentences first, otherwise every short capitalised line looks like a heading and
sentences end up split across chunks. Chunks below MIN_CHARS are merged into a neighbour, and
the "Source: ..." line and page numbers are dropped (the source URL is kept as metadata).
"""

import re
from dataclasses import asdict, dataclass

from app.data.store import Document

TARGET_CHARS = 1100  # defaults; the live values come from settings (chosen by scripts/tune_rag.py)
MAX_CHARS = 1600
MIN_CHARS = 300  # a chunk shorter than this is merged into its neighbour (headings, fragments)

PDF_TYPES = {"ar_mdna", "ar_risk", "brsr"}  # extracted from PDF annual reports
# a line ending on one of these continues on the next line (it is not a heading)
CONNECTIVES = frozenset("a an and as at by for from in into of on or the to with that which whose "
                        "your our its their is are was were be has have this these such than".split())
PAGE_NUMBER = re.compile(r"[\d\s|\-\u2013]+")

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


def _reflow(lines: list[str]) -> list[tuple[str, str]]:
    """Join PDF lines back into paragraphs. A line is a heading only if it stands alone: the text
    before it ended a sentence, it is short, has no final punctuation, does not end on a
    connective word, and the next line starts with a capital letter."""
    paragraphs: list[tuple[str, str]] = []
    section, buf = "", ""
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        ended = not buf or buf.endswith((".", "!", "?", ":", ";"))
        last = line.rsplit(" ", 1)[-1].lower()
        if (ended and len(line) <= 70 and line[0].isupper() and not line.endswith((".", ",", ";", ":"))
                and last not in CONNECTIVES and (not nxt or nxt[0].isupper())):
            if buf:
                paragraphs.append((section, buf))
                buf = ""
            section = line
        elif buf and ended and line[0].isupper():
            paragraphs.append((section, buf))
            buf = line
        elif buf.endswith("-") and line[0].islower():
            buf = buf[:-1] + line  # a word hyphenated across lines
        else:
            buf = f"{buf} {line}".strip()
    if buf:
        paragraphs.append((section, buf))
    return paragraphs


def _merge_small(chunks: list[tuple[str, str]], min_chars: int, max_chars: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for section, text in chunks:
        if out and (len(text) < min_chars or len(out[-1][1]) < min_chars) \
                and len(out[-1][1]) + len(text) + 2 <= max_chars:
            out[-1] = (out[-1][0] or section, f"{out[-1][1]}\n\n{text}")
        else:
            out.append((section, text))
    return out


def _pack(paragraphs: list[tuple[str, str]], target: int = TARGET_CHARS,
          max_chars: int = MAX_CHARS) -> list[tuple[str, str]]:
    """Greedy paragraph packing to ~target chars; overly long paragraphs are split on sentences
    (never mid-sentence), and a chunk never crosses a section heading."""
    pieces: list[tuple[str, str]] = []
    for section, para in paragraphs:
        if len(para) <= max_chars:
            pieces.append((section, para))
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        buf = ""
        for sentence in sentences:
            if buf and len(buf) + len(sentence) > target:
                pieces.append((section, buf.strip()))
                buf = ""
            buf += sentence + " "
        if buf.strip():
            pieces.append((section, buf.strip()))

    chunks: list[tuple[str, str]] = []
    section, buf = "", ""
    for sec, piece in pieces:
        if buf and (len(buf) + len(piece) > target or sec != section):
            chunks.append((section, buf.strip()))
            buf = ""
        if not buf:
            section = sec
        buf += piece + "\n\n"
    if buf.strip():
        chunks.append((section, buf.strip()))
    return _merge_small(chunks, min(MIN_CHARS, target // 2), max_chars)


def _chunk_filing(doc: Document, target: int, max_chars: int) -> list[tuple[str, str]]:
    # U+FFFD is an apostrophe or quote lost when the PDF text was extracted
    lines = doc.text.replace("\ufffd", "'").splitlines()
    body = [ln for ln in lines[1:] if not ln.startswith(("Source: ", "(Excerpt:"))]
    if doc.doc_type in PDF_TYPES:
        kept = [ln.strip() for ln in body if ln.strip() and not PAGE_NUMBER.fullmatch(ln.strip())]
        return _pack(_reflow(kept), target, max_chars)
    paragraphs: list[tuple[str, str]] = []
    section = ""
    for line in (ln.strip() for ln in body):
        if not line:
            continue
        if _is_heading(line) and not re.match(r"item\s*\d", line, flags=re.I):
            section = line
            continue
        paragraphs.append((section, line))
    return _pack(paragraphs, target, max_chars)


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


def chunk_document(doc: Document, target: int | None = None, max_chars: int | None = None) -> list[Chunk]:
    if target is None or max_chars is None:
        from app.config import get_settings

        s = get_settings()
        target, max_chars = target or s.chunk_target_chars, max_chars or s.chunk_max_chars
    if doc.doc_type == "facts":
        parts = _chunk_facts(doc)
    elif doc.doc_type == "mandate":
        parts = _chunk_mandate(doc)
    else:
        parts = _chunk_filing(doc, target, max_chars)
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
