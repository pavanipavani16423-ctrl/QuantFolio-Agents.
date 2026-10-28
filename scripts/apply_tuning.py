"""Install the best configuration from the latest RAG sweep as the live index.

The sweep (scripts/tune_rag.py) caches every embedding matrix it computes. This script copies
the one for the winning (chunk size, embedding model) into data/index/ with the manifest the
app checks at start-up, so the index does not have to be rebuilt, and prints the settings that
belong in app/config.py (the committed defaults) or .env.

    uv run python scripts/apply_tuning.py
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.data.store import documents  # noqa: E402
from app.rag.chunking import chunk_document  # noqa: E402
from app.rag.index import _corpus_hash  # noqa: E402


def main() -> None:
    tuning = sorted((ROOT / "experiments" / "results").glob("rag_tuning_*.json"))[-1]
    best = json.loads(tuning.read_text("utf-8"))["best"]
    target, max_chars = best["size"]
    chunks = [c for d in documents() for c in chunk_document(d, target, max_chars)]
    h = hashlib.sha256(best["model"].encode())
    for c in chunks:
        h.update(c.index_text.encode())
    cached = ROOT / "data" / "index_tuning" / f"{h.hexdigest()[:16]}.npy"
    folder = ROOT / "data" / "index"
    live_manifest = json.loads((folder / "manifest.json").read_text()) if (folder / "manifest.json").exists() else {}
    digest = _corpus_hash(chunks, best["model"])
    if live_manifest.get("hash") == digest:
        print("the live index already matches the best configuration")
    elif cached.exists():
        import numpy as np

        vectors = np.load(cached)
        shutil.copyfile(cached, folder / "dense.npy")
        (folder / "manifest.json").write_text(json.dumps({
            "hash": digest, "chunks": len(chunks), "model": best["model"], "dim": int(vectors.shape[1]),
            "build_seconds": None, "from": tuning.name}, indent=2))
        print(f"installed {cached.name} ({len(chunks)} chunks, dim {vectors.shape[1]}) as the live index")
    else:
        print("no cached embeddings for the best configuration; the app will rebuild the index at start-up")
    print("\nsettings:")
    print(f"  EMBEDDING_MODEL={best['model']}")
    print(f"  EMBEDDING_QUERY_PREFIX={str(best['prefix']).lower()}")
    print(f"  RERANKER_MODEL={best['reranker']}")
    print(f"  CHUNK_TARGET_CHARS={target}  CHUNK_MAX_CHARS={max_chars}")
    print(f"  RAG_CANDIDATES={best['candidates']}  RAG_RERANK_TOP={best['rerank_top']}  RAG_TOP_K={best['k']}")


if __name__ == "__main__":
    main()
