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

The index is built once from the committed corpus and cached in data/index/. Policies of
clients the advisor adds in the UI are embedded on top (a few chunks each) and swapped in as a
new index object, so a search in flight always sees one consistent index.
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
from app.data.store import Document, client_documents, documents
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


# retrieval instructions some embedding models were trained with (queries only)
QUERY_PREFIXES = {
    "snowflake/": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-": "Represent this sentence for searching relevant passages: ",
    "nomic-ai/": "search_query: ",
}


def query_prefix(model_name: str) -> str:
    from app.config import get_settings

    if not get_settings().embedding_query_prefix:
        return ""
    return next((p for k, p in QUERY_PREFIXES.items() if model_name.startswith(k)), "")


class HybridIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, embed_model, reranker,  # noqa: ANN001
                 lock: "threading.Lock | None" = None, tokens: list[list[str]] | None = None) -> None:
        self.chunks = chunks
        self.by_id = {c.chunk_id: i for i, c in enumerate(chunks)}
        self.embeddings = embeddings  # (n, d), L2-normalized
        self.embed_model = embed_model
        self.reranker = reranker
        self.digest = ""
        self.query_prefix = query_prefix(getattr(embed_model, "model_name", "") or "")
        self._tokens = tokens if tokens is not None else [tokenize(c.index_text) for c in chunks]
        self.bm25 = BM25Okapi(self._tokens)
        self._lock = lock or threading.Lock()  # onnxruntime sessions are not re-entrant across threads

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vectors = np.asarray(list(self.embed_model.passage_embed(texts, batch_size=32)), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def with_client_documents(self, docs: list[Document], drop_client: str | None = None) -> "HybridIndex":
        """A new index with `drop_client`'s policy chunks removed and `docs` added (this one is not changed)."""
        keep = [i for i, c in enumerate(self.chunks)
                if not (drop_client and c.doc_type == "mandate" and c.client_id == drop_client)]
        added = [chunk for doc in docs for chunk in chunk_document(doc)]
        vectors = self.embed_passages([c.index_text for c in added]) if added else None
        embeddings = self.embeddings[keep] if vectors is None else np.vstack([self.embeddings[keep], vectors])
        out = HybridIndex([self.chunks[i] for i in keep] + added, embeddings, self.embed_model, self.reranker,
                          lock=self._lock,
                          tokens=[self._tokens[i] for i in keep] + [tokenize(c.index_text) for c in added])
        out.digest = self.digest  # the research cache is keyed by the company corpus, unchanged here
        return out

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
            vec = np.asarray(next(iter(self.embed_model.query_embed([self.query_prefix + query]))),
                             dtype=np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)

    def rerank_scores(self, query: str, texts: list[str]) -> list[float]:
        with self._lock:
            # small batches: about the same speed on a CPU, a fraction of the peak memory of one batch
            return [float(s) for s in self.reranker.rerank(query, texts, batch_size=get_settings().rerank_batch_size)]

    # ---- search --------------------------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 6,
        mode: str = "hybrid_rerank",
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        client_id: str | None = None,
        candidates: int | None = None,
        rerank_top: int | None = None,
        market: str | None = None,
    ) -> tuple[list[Hit], SearchTrace]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        settings = get_settings()
        candidates = candidates or settings.rag_candidates
        rerank_top = rerank_top or settings.rag_rerank_top
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


# the same reranker quantised to int8 by its publisher: 35 MB of memory instead of 96 MB; on the 78
# labelled questions 93.6% hit rate and MRR 0.904 (fp32: 94.9%, 0.901). Used on the free plan.
QUANTIZED_RERANKERS = {
    "Xenova/ms-marco-MiniLM-L-6-v2-int8": ("Xenova/ms-marco-MiniLM-L-6-v2", "onnx/model_quantized.onnx"),
}


def _tune_onnx_sessions(level: str, low_memory: bool) -> None:
    """fastembed always asks ONNX for every graph optimisation and its default memory planning;
    on a small server cap both (see onnx_graph_optimization and onnx_memory_arena).

    low_memory also turns off ONNX's memory pattern: by default the first inference plans one
    buffer for all intermediate tensors of that input shape and keeps it (measured on Linux: +81 MB
    on the first query embedding)."""
    import onnxruntime as ort
    from fastembed.common import onnx_model

    if (level == "all" and not low_memory) or getattr(onnx_model.ort, "tuned", False):
        return
    chosen = {"basic": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
              "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
              "all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL}[level]

    class TunedOrt:
        tuned = True

        def __getattr__(self, name: str):  # noqa: ANN204
            return getattr(ort, name)

        @staticmethod
        def InferenceSession(path, *args, sess_options=None, **kwargs):  # noqa: ANN001, ANN205, N802
            if sess_options is not None:
                sess_options.graph_optimization_level = chosen
                if low_memory:
                    sess_options.enable_mem_pattern = False
                    sess_options.enable_cpu_mem_arena = False
            return ort.InferenceSession(path, *args, sess_options=sess_options, **kwargs)

    onnx_model.ort = TunedOrt()


def _models():  # noqa: ANN202
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    settings = get_settings()
    _tune_onnx_sessions(settings.onnx_graph_optimization, low_memory=not settings.onnx_memory_arena)
    if settings.reranker_model in QUANTIZED_RERANKERS and not any(
            m["model"] == settings.reranker_model for m in TextCrossEncoder.list_supported_models()):
        repo, file = QUANTIZED_RERANKERS[settings.reranker_model]
        TextCrossEncoder.add_custom_model(settings.reranker_model, sources=ModelSource(hf=repo), model_file=file,
                                          size_in_gb=0.03)
    cache = str(Path(settings.data_dir) / "models")
    # ONNX_THREADS=1 on small hosts: by default ONNX starts a thread per machine core, which thrashes
    # on a fractional CPU (Render's free plan has 0.1 CPU on a many-core machine)
    onnx = {"threads": settings.onnx_threads, "enable_cpu_mem_arena": settings.onnx_memory_arena}
    embed = TextEmbedding(settings.embedding_model, cache_dir=cache, **onnx)
    rerank = TextCrossEncoder(settings.reranker_model, cache_dir=cache, **onnx)
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
            meta = json.loads(meta_path.read_text("utf-8"))
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
        index = HybridIndex(chunks, embeddings, embed, rerank)
        index.digest = digest  # corpus + model version (keys the research cache)
        added = client_documents()
        _INDEX = index.with_client_documents(added) if added else index
        return _INDEX


def ensure_client(client_id: str) -> None:
    """Index an added client's policy if this process has not seen it yet."""
    from app.data import clients

    index = get_index()
    if clients.is_custom(client_id) and not any(c.client_id == client_id for c in index.chunks):
        refresh_client(client_id)


def refresh_client(client_id: str) -> None:
    """Re-index one added client's policy after it is created or removed."""
    global _INDEX
    get_index()
    docs = [d for d in client_documents() if d.client_id == client_id]
    with _BUILD_LOCK:
        _INDEX = _INDEX.with_client_documents(docs, drop_client=client_id)


def corpus_stats() -> dict:
    chunks = build_chunks()
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.doc_type] = by_type.get(c.doc_type, 0) + 1
    return {"documents": len(documents()), "chunks": len(chunks), "chunks_by_type": by_type}
