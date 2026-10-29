"""Anonymous memory (MiB) after each part of a search, in this process (run inside the container).

    python scripts/profile_memory.py

Prints one compact line, e.g. "imp 210 idx 335 emb 336 rr 352 srch 353", so CI can publish it as a
commit status.
"""

import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rss_mib() -> int:
    with open("/proc/self/status") as f:
        return next(int(line.split()[1]) // 1024 for line in f if line.startswith("RssAnon:"))


steps = []


def mark(label: str) -> None:
    steps.append(f"{label} {rss_mib()}")


mark("py")
import app.main  # noqa: E402,F401

mark("imp")
from app.rag.index import get_index, tokenize  # noqa: E402

index = get_index()
mark("idx")
query = "What climate risks do NVIDIA and NextEra disclose?"
index.embed_query(query)
mark("emb")
index.bm25.get_scores(tokenize(query))
mark("bm")
index.rerank_scores(query, [c.index_text for c in index.chunks[:10]])
mark("rr")
index.search(query, k=6, tickers=["NVDA"])
mark("srch")
for t in ("NEE", "AAPL", "MSFT"):
    index.search(query, k=6, tickers=[t])
mark("x4")
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
print(" ".join(steps) + f" hwm {peak}")
