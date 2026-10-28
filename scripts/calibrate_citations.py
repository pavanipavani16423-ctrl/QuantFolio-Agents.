"""Calibrate the citation gate's threshold for the configured reranker.

Pairs from the corpus (filings and annual reports):
* supported: a sentence, shortened like a summary (about a quarter of its words dropped), with
  the company name in front, against the passage it came from;
* hard negative: the same claim against another passage of the same company and document;
* easy negative: the same claim against a passage of another company.

The threshold is the highest score that still accepts 95% of supported claims (a gate that
blocks true claims would push good answers to the fallback). The script reports how many hard
negatives that threshold rejects and writes experiments/results/citation_calibration_<ts>.json.

    uv run python scripts/calibrate_citations.py [--pairs 300]
"""

import argparse
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.rag.index import get_index  # noqa: E402


def summarize(sentence: str, rng: random.Random) -> str:
    words = sentence.split()
    keep = [w for i, w in enumerate(words) if i < 3 or rng.random() > 0.25]
    return " ".join(keep)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=300)
    args = parser.parse_args()
    rng = random.Random(7)
    index = get_index()
    filings = [c for c in index.chunks if c.doc_type not in ("facts", "mandate") and len(c.text) > 300]
    by_doc: dict[str, list] = {}
    for c in filings:
        by_doc.setdefault(c.doc_id, []).append(c)
    rows = {"supported": [], "hard_negative": [], "easy_negative": []}
    for chunk in rng.sample(filings, min(args.pairs, len(filings))):
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", chunk.text) if 60 <= len(s) <= 300]
        same = [c for c in by_doc[chunk.doc_id] if c.chunk_id != chunk.chunk_id]
        other = [c for c in filings if c.ticker != chunk.ticker]
        if not sentences or not same:
            continue
        claim = f"{chunk.title.split(' - ')[0]}: {summarize(rng.choice(sentences), rng)}"
        texts = [chunk.text, rng.choice(same).text, rng.choice(other).text]
        s_pos, s_hard, s_easy = index.rerank_scores(claim, texts)
        rows["supported"].append(s_pos)
        rows["hard_negative"].append(s_hard)
        rows["easy_negative"].append(s_easy)
    pos = np.array(rows["supported"])
    threshold = float(np.quantile(pos, 0.05))
    result = {
        "created": datetime.now(UTC).isoformat(),
        "reranker": get_settings().reranker_model,
        "pairs": len(pos),
        "threshold": round(threshold, 3),
        "supported_accepted": round(float((pos >= threshold).mean()), 4),
        "hard_negatives_rejected": round(float((np.array(rows["hard_negative"]) < threshold).mean()), 4),
        "easy_negatives_rejected": round(float((np.array(rows["easy_negative"]) < threshold).mean()), 4),
        "quantiles": {k: [round(float(q), 3) for q in np.quantile(v, [0.05, 0.25, 0.5, 0.75, 0.95])]
                      for k, v in rows.items()},
    }
    folder = ROOT / "experiments" / "results"
    path = folder / f"citation_calibration_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2), "utf-8")
    print(json.dumps(result, indent=2))
    print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
