"""Research agent: hybrid RAG over the 10-K filings and XBRL facts, answer with citations."""

import re

from app.graph.context import RunContext
from app.rag.index import tokenize
from app.schemas import ResearchAnswer, ResearchResult, RiskFlag, Source

SYSTEM = (
    "You are an equity research analyst. Answer ONLY from the numbered sources. Cite every "
    "factual sentence with its source number in square brackets, e.g. [2]. Name the company in "
    "each sentence. If the sources do not answer part of the question, say so. Then list one "
    "risk flag per company that the sources support. Be concise and factual; no advice."
)

RISK_WORDS = set("risk risks adverse adversely harm decline reduce loss losses volatility uncertain "
                 "regulation regulatory litigation climate emissions supply shortage competition "
                 "disrupt disruption failure cyber tariffs inflation".split())


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat) if 40 <= len(s.strip()) <= 400]


def extractive_answer(question: str, sources: list[Source]) -> ResearchAnswer:
    """Rule-based answer: the most question-relevant sentence of each top source, cited."""
    q = set(tokenize(question))
    lines, flags, seen = [], [], set()
    for src in sources:
        if src.doc_type == "facts" or src.ticker in seen:
            continue
        scored = sorted(
            _sentences(src.text),
            key=lambda s: -(len(q & set(tokenize(s))) + 0.5 * len(RISK_WORDS & set(tokenize(s)))),
        )
        if not scored:
            continue
        sentence = scored[0]
        lines.append(f"{src.ticker}: {sentence} [{src.n}]")
        flags.append(RiskFlag(ticker=src.ticker or "", risk=sentence[:220], source=src.n))
        seen.add(src.ticker)
        if len(lines) == 4:
            break
    for src in sources:
        if src.doc_type == "facts":
            first = re.sub(r"\s*\(fiscal year[^)]*\)", "", src.text.splitlines()[0])
            lines.append(f"{first} [{src.n}]")
            break
    if not lines:
        return ResearchAnswer(answer="The filings in the index do not answer this question.", risk_flags=[])
    return ResearchAnswer(answer=" ".join(lines), risk_flags=flags)


def _sources(hits: list[dict], start: int) -> list[Source]:
    return [
        Source(n=start + i, chunk_id=h["chunk_id"], doc_id=h["doc_id"], doc_type=h["doc_type"],
               ticker=h.get("ticker"), title=h["title"], section=h.get("section") or "",
               source_url=h.get("source_url"), text=h["text"], rerank_score=h.get("rerank_score"),
               bm25_rank=h.get("bm25_rank"), dense_rank=h.get("dense_rank"))
        for i, h in enumerate(hits)
    ]


async def search(ctx: RunContext, query: str, **filters) -> list[dict]:  # noqa: ANN003
    """One retrieval, traced as a Langfuse retriever observation."""
    tools = ctx.toolbox("research_agent")
    with ctx.tracer.section(f"rag.search: {query[:60]}", as_type="retriever",
                            input={"query": query, **filters}) as obs:
        result = await tools.call("research", "search_documents", query=query, **filters)
        obs.update(output=[{"chunk_id": h["chunk_id"], "score": h["score"],
                            "bm25_rank": h["bm25_rank"], "dense_rank": h["dense_rank"],
                            "rerank_score": h["rerank_score"]} for h in result["hits"]],
                   metadata={"mode": result["mode"], **result["trace"]})
    return result["hits"]


def diversify(hits: list[dict], k: int) -> list[dict]:
    """Round-robin over companies in rank order, so one company cannot take every slot."""
    by_ticker: dict[str | None, list[dict]] = {}
    for h in hits:
        by_ticker.setdefault(h.get("ticker"), []).append(h)
    out: list[dict] = []
    while len(out) < k and any(by_ticker.values()):
        for group in by_ticker.values():
            if group and len(out) < k:
                out.append(group.pop(0))
    return sorted(out, key=lambda h: h["rank"])


async def run_research(ctx: RunContext, question: str, tickers: list[str]) -> ResearchResult:
    mode = ctx.settings.rag_mode
    pool = await search(ctx, question, k=20, mode=mode, tickers=tickers,
                        doc_types=["risk_factors", "mdna"])
    filings = diversify(pool, ctx.settings.rag_top_k)
    facts = await search(ctx, f"{' '.join(tickers)} total revenue net income fiscal year", k=2,
                         mode="hybrid", tickers=tickers, doc_types=["facts"])
    sources = _sources(filings, 1)
    sources += _sources([h for h in facts if h["chunk_id"] not in {s.chunk_id for s in sources}],
                        len(sources) + 1)

    # sources are trimmed in the prompt (the full text stays in the run and the UI) to fit the
    # free-tier token budget
    numbered = "\n\n".join(f"[{s.n}] {s.ticker} {s.title.split(' - ')[-1]} - {s.section}\n{s.text[:900]}"
                           for s in sources)
    answer, method = await ctx.llm.structured(
        "research_answer", ResearchAnswer, SYSTEM,
        f"Question: {question}\n\nSources:\n{numbered}",
        fallback=lambda: extractive_answer(question, sources),
    )
    valid = {s.n for s in sources}
    flags = [f for f in answer.risk_flags if f.source in valid]
    return ResearchResult(question=question, answer=answer.answer, risk_flags=flags,
                          sources=sources, method=method, retrieval_mode=mode,
                          queries=[question, f"{' '.join(tickers)} total revenue net income fiscal year"])
