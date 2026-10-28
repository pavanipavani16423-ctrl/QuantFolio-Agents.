"""Resident memory after each part of a search, in this process (run inside the container).

    python scripts/profile_memory.py

Prints one compact line, e.g. "import 210 | index 335 | embed 336 | bm25 337 | rerank 352 | search 353",
so CI can publish it as a commit status.
"""

import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rss_mib() -> int:
    with open("/proc/self/status") as f:
        return next(int(line.split()[1]) // 1024 for line in f if line.startswith("VmRSS:"))


steps = []


def mark(label: str) -> None:
    steps.append(f"{label} {rss_mib()}")


mark("python")
import app.main  # noqa: E402,F401

mark("import")
from app.rag.index import get_index, tokenize  # noqa: E402

index = get_index()
mark("index")
query = "What climate risks do NVIDIA and NextEra disclose?"
index.embed_query(query)
mark("embed")
index.bm25.get_scores(tokenize(query))
mark("bm25")
index.rerank_scores(query, [c.index_text for c in index.chunks[:10]])
mark("rerank")
index.search(query, k=6, tickers=["NVDA"])
mark("search")
for t in ("NEE", "AAPL", "MSFT"):
    index.search(query, k=6, tickers=[t])
mark("4 searches")
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
print(" | ".join(steps) + f" | max {peak}")
