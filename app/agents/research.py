"""Research agent: hybrid RAG over each market's disclosures; writes a short research report.

Retrieval runs one filtered search per company and merges them, so every company the advisor
asked about gets passages (one search over all of them lets the best-covered company take most
slots). The report has an executive summary, a section per company (key points and risks, every
sentence cited) and what the sources do not cover. Key numbers per company are computed in
code from the facts documents (app.agents.figures), never written by the model.
"""

import asyncio
import re

from app.agents.figures import key_figures
from app.data.universe import MARKETS
from app.graph.context import RunContext
from app.guardrails import Finding, worst
from app.guardrails.citations import check_support
from app.guardrails.injection import SPOTLIGHT_RULE, scan, spotlight
from app.guardrails.output import check_research, feedback
from app.rag.index import tokenize
from app.schemas import CompanyFindings, ResearchAnswer, ResearchResult, RiskFlag, Source

SYSTEM = (
    "You are an equity research analyst writing a short report for a client advisor. The sources "
    "are the companies' own regulatory disclosures (US: SEC 10-K; India: SEBI-mandated annual "
    "report MD&A, risk management and BRSR sustainability report) and reported financials. Use "
    "ONLY the numbered sources. Write: (1) an executive summary of 2-4 sentences that answers the "
    "question; (2) for each company in the sources, 2-3 key points and 1-3 risks, each one short "
    "plain sentence that names the company; (3) what the sources do not cover. Cite every "
    "sentence in (1) and (2) with its source number in square brackets, e.g. [2]. A source may "
    "only be cited for what it says: when the sources do not answer part of the question, say so "
    "in (3), without a citation, and do not repeat it in (1) or (2). Also give one risk flag per "
    "company. Be concise and factual; no advice, no predictions."
)

RISK_WORDS = set("risk risks adverse adversely harm decline reduce loss losses volatility uncertain "
                 "regulation regulatory litigation climate emissions supply shortage competition "
                 "disrupt disruption failure cyber tariffs inflation".split())


def normalize_citations(text: str) -> str:
    """Models write citations in different styles (【1】, [1][2], [1, 2], (1)); keep one: [n]."""
    text = re.sub(r"\s*\[(?:none|n/?a|no source|-)\]", "", text, flags=re.I)  # "no citation" markers
    text = re.sub(r"【\s*(\d+)\s*(?:†[^】]*)?】", r"[\1]", text)
    text = re.sub(r"\[(\d+(?:\s*,\s*\d+)+)\]", lambda m: "".join(f"[{n.strip()}]" for n in m.group(1).split(",")), text)
    return text


def _sentences(text: str) -> list[str]:
    """Whole sentences only: no headings, table rows, URLs or fragments cut at a chunk edge."""
    parts = [re.sub(r"\s+", " ", para) for para in re.split(r"\n\s*\n", text)]
    out = []
    for s in (x.strip() for flat in parts for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", flat)):
        if (40 <= len(s) <= 400 and s[0].isupper() and s.endswith((".", "!", "?"))
                and len(s.split()) >= 7 and "http" not in s and not s.startswith("Source")):
            out.append(s)
    return out


def _cite(sentence: str, n: int) -> str:
    """'... risk.' -> '... risk [3].' (the citation belongs to the sentence)."""
    return sentence.strip().rstrip(".!? ") + f" [{n}]."


def extractive_answer(question: str, sources: list[Source]) -> ResearchAnswer:
    """Rule-based report: the most question-relevant and most risk-related sentences of each
    company's sources, quoted with their citation."""
    q = set(tokenize(question))
    by_ticker: dict[str, list[Source]] = {}
    for src in sources:
        if src.doc_type != "facts" and src.ticker:
            by_ticker.setdefault(src.ticker, []).append(src)
    companies, flags, summary = [], [], []
    for ticker, srcs in by_ticker.items():
        candidates = [(s, src) for src in srcs for s in _sentences(src.text)]
        if not candidates:
            continue
        relevant = sorted(candidates, key=lambda c: -len(q & set(tokenize(c[0]))))
        risky = sorted(candidates, key=lambda c: -len(RISK_WORDS & set(tokenize(c[0]))))
        points = [_cite(s, src.n) for s, src in relevant[:2]]
        risks = [_cite(s, src.n) for s, src in risky[:2] if _cite(s, src.n) not in points][:1]
        companies.append(CompanyFindings(ticker=ticker, key_points=points, risks=risks))
        top, src = relevant[0]
        flags.append(RiskFlag(ticker=ticker, risk=(risky[0][0])[:220], source=risky[0][1].n))
        summary.append(_cite(f"{ticker}: {top}", src.n))
    if not companies:
        return ResearchAnswer(answer="The reports in the index do not answer this question.",
                              not_covered=["No matching passage was found in the companies' reports."])
    return ResearchAnswer(answer=" ".join(summary[:3]), companies=companies, risk_flags=flags,
                          not_covered=["This answer quotes the reports directly (no AI model was used)."])


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


async def per_company(ctx: RunContext, query: str, tickers: list[str], k: int, **filters) -> list[dict]:  # noqa: ANN003
    """One filtered search per company, merged in the order asked: about k passages in total and
    at least two each for up to three companies."""
    if not tickers:
        return await search(ctx, query, k=k, **filters)
    each = max(2 if len(tickers) <= 3 else 1, -(-k // len(tickers)))
    found = await asyncio.gather(*(search(ctx, query, k=each, tickers=[t], **filters) for t in tickers))
    return [hit for hits in found for hit in hits]


def quarantine(hits: list[dict], threshold: float) -> tuple[list[dict], list[dict]]:
    """Retrieval rail: passages that read like instructions to a model are kept out of the
    prompt (indirect prompt injection planted in a document)."""
    safe, held = [], []
    for h in hits:
        result = scan(h["text"])
        if result.is_attack(threshold):
            held.append({"chunk_id": h["chunk_id"], "ticker": h.get("ticker"), "title": h["title"],
                         "signals": result.signals, "score": result.score})
        else:
            safe.append(h)
    return safe, held


async def verify(ctx: RunContext, answer: str, sources: list[Source]) -> list[Finding]:
    """Format checks, then the citation gate (claim vs cited passage, cross-encoder)."""
    findings = check_research(answer, {s.n for s in sources})
    s = ctx.settings
    if s.guardrails_enabled and s.citation_gate_enabled:
        from app.rag.index import get_index

        index = await asyncio.to_thread(get_index)
        _, gate = await asyncio.to_thread(check_support, answer, {x.n: x.text for x in sources},
                                          index.rerank_scores, s.citation_support_threshold)
        findings.append(gate)
    return findings


def _clean(answer: ResearchAnswer, valid: set[int], tickers: set[str]) -> ResearchAnswer:
    answer.answer = normalize_citations(answer.answer)
    answer.risk_flags = [f for f in answer.risk_flags if f.source in valid]
    # one section per known company, in source order; citations normalised
    seen: dict[str, CompanyFindings] = {}
    for c in answer.companies:
        ticker = c.ticker.upper().strip()
        if ticker in tickers and ticker not in seen:
            seen[ticker] = CompanyFindings(ticker=ticker, key_points=[normalize_citations(x) for x in c.key_points][:3],
                                           risks=[normalize_citations(x) for x in c.risks][:3])
    answer.companies = list(seen.values())
    answer.not_covered = [x.strip() for x in answer.not_covered if x.strip()][:4]
    return answer


async def run_research(ctx: RunContext, question: str, tickers: list[str],
                       market: str = "US") -> ResearchResult:
    """Research criteria depend on the market: each market's own mandatory disclosures."""
    mode = ctx.settings.rag_mode
    threshold = ctx.settings.injection_block_threshold
    doc_types = list(MARKETS[market].research_doc_types)
    filings = await per_company(ctx, question, tickers, ctx.settings.rag_top_k, mode=mode,
                                doc_types=doc_types, market=market)
    # one reported-financials passage per company (at most four companies, to keep the prompt short)
    found = await asyncio.gather(*(search(ctx, "total revenue net income fiscal year", k=1, mode="hybrid",
                                          tickers=[t], doc_types=["facts"], market=market) for t in tickers[:4]))
    facts = [hit for hits in found for hit in hits]
    held: list[dict] = []
    if ctx.settings.guardrails_enabled:
        filings, held = quarantine(filings, threshold)
        facts, held_facts = quarantine(facts, threshold)
        held += held_facts
    sources = _sources(filings, 1)
    sources += _sources([h for h in facts if h["chunk_id"] not in {s.chunk_id for s in sources}],
                        len(sources) + 1)
    valid = {s.n for s in sources}
    known = {s.ticker for s in sources if s.ticker} | set(tickers)
    findings = [Finding("retrieval", "indirect_injection", "fixed" if held else "pass",
                        f"{len(held)} passage(s) quarantined: " + ", ".join(h["chunk_id"] for h in held)
                        if held else f"{len(sources)} passages scanned, none quarantined")]

    # sources are trimmed in the prompt (the full text stays in the run and the UI) to fit the
    # free-tier token budget; spotlighting marks them as data, not instructions
    numbered = "\n\n".join(spotlight(s.n, f"{s.ticker} {s.title.split(' - ')[-1]} - {s.section}", s.text[:ctx.settings.prompt_passage_chars])
                           for s in sources)
    system = f"{SYSTEM} {SPOTLIGHT_RULE}"
    user = f"Question: {question}\n\nSources:\n{numbered}"
    answer, method = await ctx.llm.structured("research_answer", ResearchAnswer, system, user,
                                              fallback=lambda: extractive_answer(question, sources))
    answer = _clean(answer, valid, known)
    checks = await verify(ctx, answer.text(), sources)
    corrections = 0
    if method == "llm" and worst(checks) == "block":
        # evaluator-optimizer: one more draft with the failed checks as feedback
        corrections = 1
        retry, method2 = await ctx.llm.structured(
            "research_answer_revision", ResearchAnswer, system,
            f"{user}\n\nYour previous answer:\n{answer.model_dump_json()}\n\n{feedback(checks)}",
            fallback=lambda: extractive_answer(question, sources))
        retry = _clean(retry, valid, known)
        retry_checks = await verify(ctx, retry.text(), sources)
        if method2 == "llm" and worst(retry_checks) != "block":
            failed = {f.check for f in checks if f.verdict == "block"}
            answer, checks = retry, [Finding(f.layer, f.check, "fixed", f"fixed on the second draft: {f.detail}")
                                     if f.check in failed and f.verdict != "block" else f for f in retry_checks]
        else:
            failed = "; ".join(f"{f.check}: {f.detail}" for f in [*checks, *retry_checks] if f.verdict == "block")
            answer, method = extractive_answer(question, sources), "rules_after_guardrail"
            checks = [*await verify(ctx, answer.text(), sources),
                      Finding("output", "research_fallback", "fixed",
                              f"the model's drafts failed the checks ({failed[:400]}); used the extractive answer")]
    figures = [f for f in (key_figures(t) for t in tickers) if f]
    return ResearchResult(question=question, answer=answer.answer, companies=answer.companies,
                          not_covered=answer.not_covered, key_figures=figures, risk_flags=answer.risk_flags,
                          sources=sources, method=method, retrieval_mode=mode,
                          queries=[question, "total revenue net income fiscal year (per company)"],
                          quarantined=held, guardrails=[f.to_dict() for f in findings + checks],
                          self_corrections=corrections)
