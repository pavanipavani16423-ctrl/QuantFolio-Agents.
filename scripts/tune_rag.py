"""Choose the RAG configuration by measurement: chunk size, embedding model, query prefix,
reranker, candidate pool, rerank depth and top-k.

The labelled test set (data/eval/golden_rag.json) names answer chunks of the current chunking.
To compare chunk sizes fairly, each answer chunk is turned into text anchors (the start of its
first and middle sentence); under any chunking a retrieved chunk counts as relevant when it
contains an anchor. Stages, each starting from the best result of the previous one:

    A  chunk size              (bge-small, hybrid + MiniLM-L6 rerank)
    B  embedding model + query prefix
    C  reranker
    D  candidates x rerank depth x top-k

Embeddings are cached per (model, chunking) in data/index_tuning/ (git ignored).

    uv run python scripts/tune_rag.py                # all stages, writes experiments/results/rag_tuning_<ts>.json
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.store import documents  # noqa: E402
from app.rag.chunking import chunk_document  # noqa: E402
from app.rag.index import QUERY_PREFIXES, HybridIndex, _corpus_hash  # noqa: E402

CACHE = ROOT / "data" / "index_tuning"
MODELS = ROOT / "data" / "models"
CHUNK_SIZES = [(500, 750), (800, 1150), (1100, 1600)]
EMBEDDINGS = ["BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5"]
RERANKERS = ["Xenova/ms-marco-MiniLM-L-6-v2", "Xenova/ms-marco-MiniLM-L-12-v2",
             "jinaai/jina-reranker-v1-turbo-en", "BAAI/bge-reranker-v2-m3-int8", "BAAI/bge-reranker-base"]
K = 6


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


def anchors_for(text: str) -> list[str]:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s) >= 30] or [text]
    picks = {sentences[0], sentences[len(sentences) // 2]}
    return [norm(s)[:80] for s in picks]


def golden(default_chunks: dict[str, str]) -> list[dict]:
    items = json.loads((ROOT / "data" / "eval" / "golden_rag.json").read_text("utf-8"))
    for it in items:
        it["anchors"] = [anchors_for(default_chunks[r]) for r in it["reference_ids"]]
    return items


def chunks_for(target: int, max_chars: int) -> list:
    return [c for d in documents() for c in chunk_document(d, target, max_chars)]


def embeddings(chunks: list, model: str) -> tuple[np.ndarray, object]:
    from fastembed import TextEmbedding

    h = hashlib.sha256(model.encode())
    for c in chunks:
        h.update(c.index_text.encode())
    path = CACHE / f"{h.hexdigest()[:16]}.npy"
    embedder = TextEmbedding(model, cache_dir=str(MODELS))
    if path.exists():
        return np.load(path), embedder
    live = ROOT / "data" / "index" / "manifest.json"  # reuse the live index when it matches
    if live.exists() and json.loads(live.read_text())["hash"] == _corpus_hash(chunks, model):
        return np.load(ROOT / "data" / "index" / "dense.npy"), embedder
    started = time.perf_counter()
    vectors = np.asarray(list(embedder.passage_embed([c.index_text for c in chunks], batch_size=16)),
                         dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    print(f"  embedded {len(chunks)} chunks with {model} in {time.perf_counter() - started:.0f} s", flush=True)
    return vectors, embedder


def reranker(model: str):  # noqa: ANN201
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model, cache_dir=str(MODELS))


def evaluate(index: HybridIndex, items: list[dict], mode: str = "hybrid_rerank", k: int = K,
             candidates: int = 40, rerank_top: int = 20) -> dict:
    hits, rr, recall, lat, chars = [], [], [], [], []
    by_kind: dict[str, list[float]] = {}
    for it in items:
        t0 = time.perf_counter()
        found, _ = index.search(it["question"], k=k, mode=mode, candidates=candidates, rerank_top=rerank_top)
        lat.append((time.perf_counter() - t0) * 1000)
        texts = [norm(h.chunk.text) for h in found]
        chars.append(sum(len(h.chunk.text) for h in found))
        covered = [any(any(a in t for a in ref) for t in texts) for ref in it["anchors"]]
        first = next((i for i, t in enumerate(texts, 1) if any(a in t for ref in it["anchors"] for a in ref)), None)
        hits.append(1.0 if first else 0.0)
        rr.append(1.0 / first if first else 0.0)
        recall.append(sum(covered) / len(covered))
        by_kind.setdefault(it["kind"], []).append(hits[-1])
    return {"hit_rate": round(statistics.fmean(hits), 4), "mrr": round(statistics.fmean(rr), 4),
            "recall": round(statistics.fmean(recall), 4), "latency_ms": round(statistics.median(lat), 1),
            "context_chars": round(statistics.fmean(chars)),
            "by_kind": {kind: round(statistics.fmean(v), 4) for kind, v in by_kind.items()}}


def better(a: dict, b: dict | None) -> bool:
    """Rank by hit rate, then MRR; small differences (< 1 question) prefer the cheaper setup."""
    if b is None:
        return True
    return (a["hit_rate"], a["mrr"]) > (b["hit_rate"], b["mrr"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", default="ABCD")
    args = parser.parse_args()
    default = {c.chunk_id: c.text for c in chunks_for(1100, 1600)}
    items = golden(default)
    print(f"test set: {len(items)} questions", flush=True)
    out: dict = {"created": datetime.now(UTC).isoformat(), "k": K, "items": len(items), "stages": {}}
    rerank_l6 = reranker(RERANKERS[0])

    def build(size: tuple[int, int], model: str, prefix: bool, rr) -> HybridIndex:  # noqa: ANN001
        chunks = chunks_for(*size)
        vectors, embedder = embeddings(chunks, model)
        index = HybridIndex(chunks, vectors, embedder, rr)
        index.query_prefix = next((p for key, p in QUERY_PREFIXES.items() if model.startswith(key)), "") if prefix else ""
        return index

    best = {"size": (1100, 1600), "model": "BAAI/bge-small-en-v1.5", "prefix": False,
            "reranker": RERANKERS[0], "candidates": 40, "rerank_top": 20, "k": K}

    if "A" in args.stages:
        rows, top = [], None
        for size in CHUNK_SIZES:
            index = build(size, best["model"], False, rerank_l6)
            for mode in ("dense", "hybrid", "hybrid_rerank"):
                m = evaluate(index, items, mode)
                rows.append({"chunk_target": size[0], "chunks": len(index.chunks), "mode": mode, **m})
                print(f"A size={size[0]:5d} {mode:14s} {m}", flush=True)
                if mode == "hybrid_rerank" and better(m, top):
                    top, best["size"] = m, size
        out["stages"]["A_chunk_size"] = rows

    save(out, best)

    if "B" in args.stages:
        rows, top = [], None
        for model in EMBEDDINGS:
            for prefix in (False, True):
                index = build(best["size"], model, prefix, rerank_l6)
                for mode in ("dense", "hybrid_rerank"):
                    m = evaluate(index, items, mode)
                    rows.append({"embedding": model, "query_prefix": prefix, "mode": mode, **m})
                    print(f"B {model:38s} prefix={prefix!s:5s} {mode:14s} {m}", flush=True)
                    if mode == "hybrid_rerank" and better(m, top):
                        top, best["model"], best["prefix"] = m, model, prefix
        out["stages"]["B_embedding"] = rows

    save(out, best)

    if "C" in args.stages:
        rows, top = [], None
        for name in RERANKERS:
            try:
                rr = rerank_l6 if name == RERANKERS[0] else reranker(name)
            except Exception as exc:  # noqa: BLE001 - a model that cannot be downloaded is skipped
                print(f"C {name}: skipped ({exc})", flush=True)
                continue
            index = build(best["size"], best["model"], best["prefix"], rr)
            m = evaluate(index, items, "hybrid_rerank")
            rows.append({"reranker": name, **m})
            print(f"C {name:40s} {m}", flush=True)
            if better(m, top):
                top, best["reranker"] = m, name
        out["stages"]["C_reranker"] = rows

    save(out, best)

    if "D" in args.stages:
        rows, top = [], None
        index = build(best["size"], best["model"], best["prefix"],
                      rerank_l6 if best["reranker"] == RERANKERS[0] else reranker(best["reranker"]))
        for candidates in (20, 40):
            for rerank_top in (10, 20, 30):
                m = evaluate(index, items, "hybrid_rerank", K, candidates, rerank_top)
                rows.append({"candidates": candidates, "rerank_top": rerank_top, "k": K, **m})
                print(f"D candidates={candidates} rerank_top={rerank_top} {m}", flush=True)
                # deeper reranking costs latency: only take it for a real gain
                if top is None or (m["hit_rate"], m["mrr"]) > (top["hit_rate"] + 0.012, top["mrr"] + 0.01):
                    top, best["candidates"], best["rerank_top"] = m, candidates, rerank_top
        for k in (4, 6, 8):
            m = evaluate(index, items, "hybrid_rerank", k, best["candidates"], best["rerank_top"])
            rows.append({"candidates": best["candidates"], "rerank_top": best["rerank_top"], "k": k, **m})
            print(f"D k={k} {m}", flush=True)
        out["stages"]["D_depth"] = rows

    path = save(out, best)
    print("best", out["best"], flush=True)
    print("wrote", path.relative_to(ROOT), flush=True)


PATH: list[Path] = []


def save(out: dict, best: dict) -> Path:
    """Write (or overwrite) this sweep's result file; called after every stage."""
    out["best"] = {**best, "size": list(best["size"])}
    if not PATH:
        folder = ROOT / "experiments" / "results"
        folder.mkdir(parents=True, exist_ok=True)
        PATH.append(folder / f"rag_tuning_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    PATH[0].write_text(json.dumps(out, indent=2), "utf-8")
    return PATH[0]


if __name__ == "__main__":
    main()
