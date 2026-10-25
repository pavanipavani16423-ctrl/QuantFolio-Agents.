"""Hybrid retrieval over SEC filings, financial facts and client mandates.

Pipeline (mode ``hybrid_rerank``, the default):

1. metadata filter (tickers, document types, client)
2. BM25 keyword search            -> top `candidates`
3. dense search (bge-small, cosine) -> top `candidates`
4. Reciprocal Rank Fusion (k=60) of the two lists
5. cross-encoder rerank (ms-marco MiniLM) of the fused candidates -> top `k`

Why hybrid: finance questions mix exact tokens (tickers, "Item 1A", "$215.9 billion",
"Section 3.2") that keyword search finds reliably with paraphrased concepts ("supply chain
concentration") that embeddings find better. The other modes exist so the evaluation can
measure each stage on its own.

The index is built once from the committed corpus and cached in data/index/.
"""

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.data.store import documents
from app.rag.chunking import Chunk, chunk_document

logger = logging.getLogger(__name__)

RRF_K = 60
MODES = ("bm25", "dense", "hybrid", "hybrid_rerank")

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the their this "
    "to was were what which with how does do did will would can could should about over under "
    "than any all our we they them there these those such may also".split()
)


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[.'][a-z0-9]+)*", text.lower())
    return [t for t in tokens if t not in STOPWORDS]


@dataclass
class Hit:
    chunk: Chunk
    score: float
    rank: int
    bm25_rank: int | None = None
    dense_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    def to_dict(self, max_chars: int | None = None) -> dict:
        text = self.chunk.text if max_chars is None else self.chunk.text[:max_chars]
        return {
            "chunk_id": self.chunk.chunk_id,
            "doc_id": self.chunk.doc_id,
            "doc_type": self.chunk.doc_type,
            "ticker": self.chunk.ticker,
            "client_id": self.chunk.client_id,
            "title": self.chunk.title,
            "section": self.chunk.section,
            "source_url": self.chunk.source_url,
            "market": self.chunk.market,
            "text": text,
            "score": round(float(self.score), 6),
            "rank": self.rank,
            "bm25_rank": self.bm25_rank,
            "dense_rank": self.dense_rank,
            "rrf_score": None if self.rrf_score is None else round(self.rrf_score, 6),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
        }


@dataclass
class SearchTrace:
    """Per-stage details, recorded in the Langfuse retriever span."""

    mode: str
    filtered_pool: int
    bm25_top: list[str] = field(default_factory=list)
    dense_top: list[str] = field(default_factory=list)
    fused_top: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


class HybridIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, embed_model, reranker) -> None:  # noqa: ANN001
        self.chunks = chunks
        self.by_id = {c.chunk_id: i for i, c in enumerate(chunks)}
        self.embeddings = embeddings  # (n, d), L2-normalized
        self.embed_model = embed_model
        self.reranker = reranker
        self.bm25 = BM25Okapi([tokenize(c.index_text) for c in chunks])
        self._lock = threading.Lock()  # onnxruntime sessions are not re-entrant across threads

    # ---- filters -------------------------------------------------------------------------
    def _mask(self, tickers, doc_types, client_id, market=None) -> np.ndarray:  # noqa: ANN001
        mask = np.ones(len(self.chunks), dtype=bool)
        if market:
            mask &= np.array([c.market in (None, market) for c in self.chunks])
        if tickers:
            wanted = {t.upper() for t in tickers}
            mask &= np.array([c.ticker in wanted for c in self.chunks])
        if doc_types:
            mask &= np.array([c.doc_type in doc_types for c in self.chunks])
        if client_id:
            mask &= np.array(
                [c.client_id in (None, client_id) and (c.doc_type != "mandate" or c.client_id == client_id)
                 for c in self.chunks]
            )
        return mask

    def _top(self, scores: np.ndarray, mask: np.ndarray, n: int) -> list[int]:
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return []
        order = idx[np.argsort(-scores[idx], kind="stable")]
        return [int(i) for i in order[:n]]

    def embed_query(self, query: str) -> np.ndarray:
        with self._lock:
            vec = np.asarray(next(iter(self.embed_model.query_embed([query]))), dtype=np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)

    def rerank_scores(self, query: str, texts: list[str]) -> list[float]:
        with self._lock:
            return [float(s) for s in self.reranker.rerank(query, texts)]

    # ---- search --------------------------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 6,
        mode: str = "hybrid_rerank",
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        client_id: str | None = None,
        candidates: int = 40,
        rerank_top: int = 20,
        market: str | None = None,
    ) -> tuple[list[Hit], SearchTrace]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        mask = self._mask(tickers, doc_types, client_id, market)
        trace = SearchTrace(mode=mode, filtered_pool=int(mask.sum()))
        t0 = time.perf_counter()

        bm25_rank: dict[int, int] = {}
        dense_rank: dict[int, int] = {}
        if mode in ("bm25", "hybrid", "hybrid_rerank"):
            scores = np.asarray(self.bm25.get_scores(tokenize(query)))
            top = self._top(scores, mask, candidates)
            # BM25 gives 0 to chunks sharing no query term; they are not real matches
            top = [i for i in top if scores[i] > 0]
            bm25_rank = {i: r for r, i in enumerate(top, 1)}
            bm25_scores = scores
            trace.bm25_top = [self.chunks[i].chunk_id for i in top[:10]]
            trace.timings_ms["bm25"] = round((time.perf_counter() - t0) * 1000, 2)
        if mode in ("dense", "hybrid", "hybrid_rerank"):
            t1 = time.perf_counter()
            sims = self.embeddings @ self.embed_query(query)
            top = self._top(sims, mask, candidates)
            dense_rank = {i: r for r, i in enumerate(top, 1)}
            dense_scores = sims
            trace.dense_top = [self.chunks[i].chunk_id for i in top[:10]]
            trace.timings_ms["dense"] = round((time.perf_counter() - t1) * 1000, 2)

        if mode == "bm25":
            ranked = [(i, float(bm25_scores[i])) for i in bm25_rank]
            hits = [Hit(self.chunks[i], s, r, bm25_rank=r) for r, (i, s) in enumerate(ranked[:k], 1)]
            return hits, trace
        if mode == "dense":
            ranked = [(i, float(dense_scores[i])) for i in dense_rank]
            hits = [Hit(self.chunks[i], s, r, dense_rank=r) for r, (i, s) in enumerate(ranked[:k], 1)]
            return hits, trace

        fused: dict[int, float] = {}
        for ranks in (bm25_rank, dense_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
        order = sorted(fused, key=lambda i: -fused[i])[:candidates]
        trace.fused_top = [self.chunks[i].chunk_id for i in order[:10]]

        def hit(i: int, score: float, rank: int, rerank: float | None = None) -> Hit:
            return Hit(self.chunks[i], score, rank, bm25_rank=bm25_rank.get(i),
                       dense_rank=dense_rank.get(i), rrf_score=fused[i], rerank_score=rerank)

        if mode == "hybrid":
            return [hit(i, fused[i], r) for r, i in enumerate(order[:k], 1)], trace

        # the cross-encoder is the slow stage (~0.1 s per pair on a laptop CPU): rerank the
        # head of the fused list only
        order = order[:rerank_top]
        t2 = time.perf_counter()
        scores = self.rerank_scores(query, [self.chunks[i].index_text for i in order]) if order else []
        trace.timings_ms["rerank"] = round((time.perf_counter() - t2) * 1000, 2)
        reranked = sorted(zip(order, scores, strict=True), key=lambda p: -p[1])
        return [hit(i, s, r, rerank=s) for r, (i, s) in enumerate(reranked[:k], 1)], trace

    def get(self, chunk_id: str) -> Chunk:
        return self.chunks[self.by_id[chunk_id]]


# ---- build / load -------------------------------------------------------------------------

_INDEX: HybridIndex | None = None
_BUILD_LOCK = threading.Lock()


def _index_dir() -> Path:
    return Path(get_settings().data_dir) / "index"


def _corpus_hash(chunks: list[Chunk], model: str) -> str:
    h = hashlib.sha256(model.encode())
    for c in chunks:
        h.update(c.chunk_id.encode())
        h.update(c.index_text.encode())
    return h.hexdigest()[:16]


def _models():  # noqa: ANN202
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    settings = get_settings()
    cache = str(Path(settings.data_dir) / "models")
    embed = TextEmbedding(settings.embedding_model, cache_dir=cache)
    rerank = TextCrossEncoder(settings.reranker_model, cache_dir=cache)
    return embed, rerank


def build_chunks() -> list[Chunk]:
    return [chunk for doc in documents() for chunk in chunk_document(doc)]


def get_index() -> HybridIndex:
    """The process-wide index; built (about a minute on a laptop CPU) on first use."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _BUILD_LOCK:
        if _INDEX is not None:
            return _INDEX
        settings = get_settings()
        chunks = build_chunks()
        embed, rerank = _models()
        digest = _corpus_hash(chunks, settings.embedding_model)
        folder = _index_dir()
        meta_path, vec_path = folder / "manifest.json", folder / "dense.npy"
        embeddings = None
        if meta_path.exists() and vec_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("hash") == digest:
                embeddings = np.load(vec_path)
        if embeddings is None:
            started = time.perf_counter()
            logger.info("building dense index", extra={"fields": {"chunks": len(chunks)}})
            vectors = np.asarray(
                list(embed.passage_embed([c.index_text for c in chunks], batch_size=32)),
                dtype=np.float32,
            )
            embeddings = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
            folder.mkdir(parents=True, exist_ok=True)
            np.save(vec_path, embeddings)
            meta_path.write_text(json.dumps({
                "hash": digest, "chunks": len(chunks), "model": settings.embedding_model,
                "dim": int(embeddings.shape[1]),
                "build_seconds": round(time.perf_counter() - started, 1),
            }, indent=2))
        _INDEX = HybridIndex(chunks, embeddings, embed, rerank)
        return _INDEX


def corpus_stats() -> dict:
    chunks = build_chunks()
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.doc_type] = by_type.get(c.doc_type, 0) + 1
    return {"documents": len(documents()), "chunks": len(chunks), "chunks_by_type": by_type}
