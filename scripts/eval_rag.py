"""Offline RAG evaluation on a labelled test set, logged to Langfuse as experiments.

Test set (data/eval/golden_rag.json, rebuilt by this script):
* facts    - one revenue question per company, generated from the SEC XBRL facts documents;
* mandate  - three questions per client about the investment policy statements;
* risk     - 18 hand-written questions paraphrasing a specific 10-K risk-factor passage
             (deliberately in different words than the filing, so keyword search alone
             cannot just match them).
Every item lists the chunk ids that contain the answer.

For each retrieval mode (bm25, dense, hybrid, hybrid_rerank) the script retrieves the top k
over the WHOLE corpus (no filters) and scores:
* hit_rate@k, recall@k, mrr@k                    (classic IR metrics)
* ragas_id_context_precision / _recall           (RAGAS ID-based context metrics, no LLM)
* with a judge LLM (GROQ_API_KEY etc.): RAGAS faithfulness and factual correctness of an
  answer generated from the retrieved context (hybrid_rerank only, to bound cost).

Results go to experiments/results/rag_eval_<timestamp>.json and, when Langfuse keys are
set, to a Langfuse dataset ("quantfolio-rag-golden") with one experiment run per mode.

    uv run python scripts/eval_rag.py [--k 6] [--no-langfuse] [--llm-items 12]
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.data import store  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.rag.index import MODES, build_chunks, get_index  # noqa: E402

DATASET = "quantfolio-rag-golden"

# (question, primary chunk id). Chunks that are only a risk-factor heading also count the
# paragraph that follows them (see `references`).
RISK_QUESTIONS = [
    ("How could US import tariffs and geopolitical tension affect Apple's supply chain?", "AAPL_risk_factors#007"),
    ("Why does the state of the world economy matter so much to Apple's results?", "AAPL_risk_factors#001"),
    ("What harm could hacking or security flaws cause Microsoft?", "MSFT_risk_factors#024"),
    ("Why might NVIDIA end up with too much or too little product compared to what customers want?", "NVDA_risk_factors#014"),
    ("How do currency movements affect Amazon's international results?", "AMZN_risk_factors#021"),
    ("How does government supervision shape the way JPMorgan runs its business?", "JPM_risk_factors#009"),
    ("Could lawsuits or government probes hurt Visa?", "V_risk_factors#038"),
    ("What happens to UnitedHealth if it misjudges how much patient care will cost?", "UNH_risk_factors#004"),
    ("How dependent is Pfizer on a small number of its best-selling drugs?", "PFE_risk_factors#011"),
    ("Why are fake medicines a risk for Pfizer?", "PFE_risk_factors#030"),
    ("How could countries' net-zero climate policies affect ExxonMobil?", "XOM_risk_factors#018"),
    ("Could worries about sugar and weight gain reduce demand for Coca-Cola drinks?", "KO_risk_factors#024"),
    ("Why are relationships with bottlers important to Coca-Cola?", "KO_risk_factors#044"),
    ("How could a disease outbreak affect Walmart?", "WMT_risk_factors#018"),
    ("What would new limits on carbon emissions mean for NextEra Energy?", "NEE_risk_factors#019"),
    ("What is the biggest cost in making Linde's industrial gases, and how does Linde manage it?", "LIN_risk_factors#003"),
    ("Why is Caterpillar sensitive to the economic cycle?", "CAT_risk_factors#004"),
    ("Why does Home Depot care so much about its brand and reputation?", "HD_risk_factors#002"),
]

# India: hand-written, reworded questions about SEBI annual-report and BRSR passages. The answer
# chunk is located by a short anchor phrase from the passage (chunk ids depend on chunking).
RISK_QUESTIONS_IN = [
    ("Which international standards does TCS follow to manage enterprise risk?", "COSO 2017 and ISO 31000"),
    ("What types of risk does HDFC Bank say it has to manage?", "credit, market, liquidity, operational, model, cybersecurity"),
    ("What dangers come with Bharti Airtel running businesses in Asia and Africa?", "Operating across diverse and dynamic markets in Asia and Africa"),
    ("How does Hindustan Unilever decide whether a sustainability issue really matters?", "A sustainability issue is considered material if"),
    ("According to TCS, how did conflict and trade disruption change energy prices and costs?", "volatility in oil and gas prices due to supply risks"),
    ("What hit Maruti Suzuki's business environment late in the year, and what happened to the rupee?", "West Asia conflict created supply and cost shocks"),
    ("What does Reliance expect for global oil demand next year, and why?", "Global oil demand growth is expected to be sluggish"),
    ("How many steps are in Asian Paints' process for handling risks?", "five-stage risk management process"),
    ("How did L&T narrow down which sustainability topics matter most?", "An initial longlist of 34 topics"),
    ("Which committee oversees business risks at Titan, and which risks does it cover?", "The Company has constituted a Risk Management Committee"),
]

MANDATE_QUESTIONS = [
    ("How many stocks must {name}'s portfolio hold?", r"hold exactly \d+ stocks"),
    ("What is the largest share of {name}'s portfolio one stock may have?", r"no single holding may exceed"),
    ("Which industries or companies does {name} exclude from its portfolio?", r"Excluded sectors"),
]


def build_golden() -> list[dict]:
    chunks = build_chunks()
    by_id = {c.chunk_id: c for c in chunks}
    ordered = [c.chunk_id for c in chunks]

    def references(primary: str) -> list[str]:
        refs = [primary]
        if len(by_id[primary].text) < 220:  # a heading: the next paragraph holds the detail
            nxt = ordered[ordered.index(primary) + 1]
            if by_id[nxt].doc_id == by_id[primary].doc_id:
                refs.append(nxt)
        return refs

    items = []
    for c in chunks:
        if c.doc_type == "facts" and c.section.lower() == "total revenue":
            first = c.text.splitlines()[0]
            m = re.search(r"of ([$₹][\d.,]+ \w+) for the fiscal year ended (\S+) \(fiscal year (\d+)", first)
            name = store.company_name(c.ticker)
            items.append({
                "id": f"facts-{c.ticker}",
                "kind": "facts",
                "question": f"What total revenue did {name} report for fiscal year {m.group(3)}?",
                "reference": f"{name} reported total revenue of {m.group(1)} for the fiscal year ended {m.group(2)}.",
                "reference_ids": [c.chunk_id],
            })
    for cid, acc in store.accounts().items():
        mandate = [c for c in chunks if c.doc_type == "mandate" and c.client_id == cid]
        for i, (template, pattern) in enumerate(MANDATE_QUESTIONS):
            hit = next(c for c in mandate if re.search(pattern, c.text, re.I))
            sentence = next(s for s in hit.text.split("\n") if re.search(pattern, s, re.I))
            items.append({
                "id": f"mandate-{cid}-{i}",
                "kind": "mandate",
                "question": template.format(name=acc["name"]),
                "reference": sentence.strip(),
                "reference_ids": [hit.chunk_id],
            })
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).lower()

    for i, (question, anchor) in enumerate(RISK_QUESTIONS_IN):
        hit = next((c for c in chunks if c.market == "IN" and norm(anchor) in norm(c.text)), None)
        if hit is None:
            print(f"warning: anchor not found, skipping: {anchor!r}")
            continue
        items.append({
            "id": f"risk-in-{i:02d}",
            "kind": "risk_india",
            "question": question,
            "reference": hit.text[:1200],
            "reference_ids": [hit.chunk_id],
        })
    for i, (question, primary) in enumerate(RISK_QUESTIONS):
        refs = references(primary)
        items.append({
            "id": f"risk-{i:02d}",
            "kind": "risk",
            "question": question,
            "reference": " ".join(by_id[r].text for r in refs)[:1200],
            "reference_ids": refs,
        })
    return items


def ir_metrics(retrieved: list[str], relevant: list[str], k: int) -> dict[str, float]:
    top = retrieved[:k]
    rel = set(relevant)
    first = next((i for i, cid in enumerate(top, 1) if cid in rel), None)
    return {
        f"hit_rate@{k}": 1.0 if first else 0.0,
        f"recall@{k}": len(rel & set(top)) / len(rel),
        f"mrr@{k}": 1.0 / first if first else 0.0,
    }


async def ragas_id_metrics(retrieved: list[str], relevant: list[str]) -> dict[str, float]:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall

    sample = SingleTurnSample(retrieved_context_ids=retrieved, reference_context_ids=relevant)
    return {
        "ragas_id_context_precision": float(await IDBasedContextPrecision().single_turn_ascore(sample)),
        "ragas_id_context_recall": float(await IDBasedContextRecall().single_turn_ascore(sample)),
    }


def retrieve(question: str, mode: str, k: int) -> tuple[list[dict], float]:
    started = time.perf_counter()
    hits, _ = get_index().search(question, k=k, mode=mode)
    return [h.to_dict() for h in hits], (time.perf_counter() - started) * 1000


async def llm_answer_metrics(settings, items: list[dict], k: int) -> tuple[dict | None, str | None, list[str]]:  # noqa: ANN001
    """RAGAS faithfulness + factual correctness of LLM answers from hybrid_rerank context."""
    from app.evaluation.ragas_adapters import make_judge
    from app.llm.gateway import LLMGateway
    from app.schemas import ResearchAnswer

    judge = make_judge(settings)
    llm = LLMGateway(settings)
    if judge is None or not llm.available:
        return None, None, ["LLM-judged RAGAS metrics skipped: no LLM key configured"]
    from ragas.metrics.collections import FactualCorrectness, Faithfulness

    faith, fact = Faithfulness(llm=judge), FactualCorrectness(llm=judge)
    scores = {"ragas_faithfulness": [], "ragas_factual_correctness": []}
    notes = []
    for item in items:
        hits, _ = retrieve(item["question"], "hybrid_rerank", k)
        numbered = "\n\n".join(f"[{i}] {h['text']}" for i, h in enumerate(hits, 1))
        answer, method = await llm.structured(
            "eval_answer", ResearchAnswer,
            "Answer only from the numbered sources; cite them as [n]. Two to four sentences.",
            f"Question: {item['question']}\n\nSources:\n{numbered}",
            fallback=lambda: ResearchAnswer(answer="", risk_flags=[]))
        if method != "llm" or not answer.answer:
            notes.append(f"{item['id']}: no LLM answer")
            continue
        contexts = [h["text"] for h in hits]
        for name, coro in (("ragas_faithfulness", faith.ascore(user_input=item["question"], response=answer.answer, retrieved_contexts=contexts)),
                           ("ragas_factual_correctness", fact.ascore(response=answer.answer, reference=item["reference"]))):
            try:
                scores[name].append(float((await coro).value))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{item['id']} {name}: {type(exc).__name__}")
    means = {k: (statistics.fmean(v) if v else None) for k, v in scores.items()}
    return {"hybrid_rerank": means}, judge.model_name, notes


def log_to_langfuse(items: list[dict], k: int) -> tuple[str | None, list[dict]]:
    from app.observability.tracing import get_tracer

    tracer = get_tracer()
    if not tracer.enabled:
        return None, []
    lf = tracer.client
    try:
        lf.create_dataset(name=DATASET, description="QuantFolio RAG test set: facts, mandate and paraphrased risk questions (US 10-K and Indian annual reports) with the chunk ids that answer them.")
    except Exception:  # noqa: BLE001 - already exists
        pass
    for it in items:
        lf.create_dataset_item(dataset_name=DATASET, id=f"{DATASET}-{it['id']}", input={"question": it["question"]},
                               expected_output={"reference": it["reference"], "reference_ids": it["reference_ids"]},
                               metadata={"kind": it["kind"]})
    dataset = lf.get_dataset(DATASET)
    from langfuse import Evaluation

    runs = []
    for mode in MODES:
        def task(*, item, mode=mode, **_):  # noqa: ANN001, ANN202
            hits, latency = retrieve(item.input["question"], mode, k)
            return {"chunk_ids": [h["chunk_id"] for h in hits], "latency_ms": round(latency, 1)}

        # Async: this runs inside main()'s event loop, where asyncio.run() is not allowed.
        async def ir_evaluator(*, input, output, expected_output, **_):  # noqa: A002, ANN001, ANN202
            m = ir_metrics(output["chunk_ids"], expected_output["reference_ids"], k)
            ragas = await ragas_id_metrics(output["chunk_ids"], expected_output["reference_ids"])
            return [Evaluation(name=n, value=v) for n, v in {**m, **ragas}.items()]

        def run_average(*, item_results, **_):  # noqa: ANN001, ANN202
            values = [e.value for r in item_results for e in r.evaluations if e.name == f"hit_rate@{k}"]
            return Evaluation(name=f"avg_hit_rate@{k}", value=statistics.fmean(values) if values else 0.0)

        result = lf.run_experiment(name=f"retrieval-{mode}", run_name=f"retrieval-{mode}-{datetime.now(UTC):%Y%m%d-%H%M}",
                                   description=f"Top-{k} retrieval with mode {mode}", data=dataset.items, task=task,
                                   evaluators=[ir_evaluator], run_evaluators=[run_average], max_concurrency=1,
                                   metadata={"mode": mode, "k": str(k)})
        runs.append({"mode": mode, "url": getattr(result, "experiment_url", None) or getattr(result, "dataset_run_url", None)})
    lf.flush()
    return DATASET, runs


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--no-langfuse", action="store_true")
    parser.add_argument("--llm-items", type=int, default=8, help="items for LLM-judged metrics (half US, half India)")
    args = parser.parse_args()
    setup_logging("WARNING")
    settings = get_settings()

    items = build_golden()
    (ROOT / "data" / "eval" / "golden_rag.json").write_text(json.dumps(items, indent=1), "utf-8")
    kinds: dict[str, int] = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    print(f"test set: {len(items)} items {kinds}")
    get_index()

    modes: dict[str, dict] = {}
    per_kind: dict[str, dict] = {}
    for mode in MODES:
        rows, latencies = [], []
        for it in items:
            hits, latency = retrieve(it["question"], mode, args.k)
            ids = [h["chunk_id"] for h in hits]
            row = {**ir_metrics(ids, it["reference_ids"], args.k), **await ragas_id_metrics(ids, it["reference_ids"]),
                   "kind": it["kind"]}
            rows.append(row)
            latencies.append(latency)
        names = [n for n in rows[0] if n != "kind"]
        modes[mode] = {n: round(statistics.fmean(r[n] for r in rows), 4) for n in names}
        modes[mode]["latency_ms"] = round(statistics.median(latencies), 1)
        per_kind[mode] = {kind: round(statistics.fmean(r[f"hit_rate@{args.k}"] for r in rows if r["kind"] == kind), 4)
                          for kind in kinds}
        print(f"{mode:14s} " + " ".join(f"{n}={v}" for n, v in modes[mode].items()) + f"  by kind {per_kind[mode]}")

    # Half US, half India risk questions, so the judged sample covers both markets.
    us_n = args.llm_items // 2
    judged = ([it for it in items if it["kind"] == "risk"][:us_n]
              + [it for it in items if it["kind"] == "risk_india"][: args.llm_items - us_n])
    llm_metrics, judge, llm_notes = await llm_answer_metrics(settings, judged, args.k)

    dataset, runs = (None, []) if args.no_langfuse else log_to_langfuse(items, args.k)
    best = max(modes, key=lambda m: modes[m][f"hit_rate@{args.k}"])
    notes = [
        f"Retrieval over the whole corpus ({len(build_chunks())} chunks), no metadata filters, top {args.k}.",
        f"Best hit rate: {best} ({modes[best][f'hit_rate@{args.k}']:.0%}).",
        "Hit rate by question type: " + "; ".join(f"{m}: " + ", ".join(f"{k} {v:.0%}" for k, v in per_kind[m].items()) for m in MODES) + ".",
        "Latency is the median per query on this laptop CPU (the reranker dominates).",
        *llm_notes,
    ]
    out = {
        "created": datetime.now(UTC).isoformat(),
        "dataset": {"name": DATASET, "items": len(items), "by_kind": kinds,
                    "source": "data/eval/golden_rag.json (generated from the corpus + 18 US and 10 India hand-written risk questions)"},
        "k": args.k,
        "modes": modes,
        "by_kind": per_kind,
        "llm": {"judge": judge, "metrics": llm_metrics},
        "langfuse": {"dataset": dataset, "runs": runs},
        "notes": notes,
    }
    folder = ROOT / "experiments" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rag_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2), "utf-8")
    print("wrote", path.relative_to(ROOT))
    for r in runs:
        print("langfuse", r["mode"], r["url"])


if __name__ == "__main__":
    asyncio.run(main())
