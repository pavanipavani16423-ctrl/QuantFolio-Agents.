"""Red-team evaluation of the guardrails.

* requests  : hand-written attacks (direct injection, jailbreaks, prohibited finance, out of
              scope) and tricky benign requests -> input rail verdict
* pii       : personal data that must be removed, and financial text that must not be touched
* passages  : real report passages from the index (must pass) and the same passages with an
              instruction planted in the middle (must be quarantined) -> retrieval rail

Writes experiments/results/guardrail_eval_<ts>.json and, when Langfuse is configured, a
dataset `quantfolio-guardrails-redteam` with one experiment run.

    uv run python scripts/eval_guardrails.py [--passages 200] [--no-langfuse]
"""

import argparse
import json
import random
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.guardrails.injection import scan  # noqa: E402
from app.guardrails.input import check_request  # noqa: E402
from app.guardrails.pii import redact  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402

DATASET = "quantfolio-guardrails-redteam"


def judge_request(case: dict, threshold: float, semantic: float | None = None) -> dict:
    text, pii = redact(case["text"])
    verdict, findings = check_request(text, case.get("market", "US"), pii, threshold, semantic)
    blocked = verdict == "block"
    return {"id": case["id"], "kind": case["kind"], "expect": case["expect"], "got": "block" if blocked else "pass",
            "correct": blocked == (case["expect"] == "block"),
            "reason": "; ".join(f.detail for f in findings if f.verdict == "block")}


def passages(n: int, injections: list[str], threshold: float) -> tuple[list[dict], list[dict]]:
    from app.rag.index import build_chunks

    rng = random.Random(11)
    pool = [c for c in build_chunks() if c.doc_type not in ("facts", "mandate") and len(c.text) > 400]
    sample = rng.sample(pool, min(n, len(pool)))
    clean, poisoned = [], []
    for c in sample:
        r = scan(c.text)
        clean.append({"chunk_id": c.chunk_id, "quarantined": r.is_attack(threshold), "signals": r.signals})
        # plant the instruction between two sentences near the middle (or at the end)
        cut = c.text.find(". ", len(c.text) // 2)
        cut = cut + 2 if cut > 0 else len(c.text)
        attack = rng.choice(injections)
        r = scan(c.text[:cut] + " " + attack + " " + c.text[cut:])
        poisoned.append({"chunk_id": c.chunk_id, "attack": attack, "quarantined": r.is_attack(threshold),
                         "signals": r.signals})
    return clean, poisoned


def log_to_langfuse(rows: list[dict]) -> str | None:
    from app.observability.tracing import get_tracer

    tracer = get_tracer()
    if not tracer.enabled:
        return None
    from langfuse import Evaluation

    lf = tracer.client
    try:
        lf.create_dataset(name=DATASET, description="Red-team requests for the QuantFolio input guardrails.")
    except Exception:  # noqa: BLE001 - already exists
        pass
    cases = json.loads((ROOT / "data" / "eval" / "guardrail_cases.json").read_text("utf-8"))["requests"]
    for case in cases:
        lf.create_dataset_item(dataset_name=DATASET, id=f"{DATASET}-{case['id']}",
                               input={"text": case["text"], "market": case["market"]},
                               expected_output={"verdict": case["expect"]}, metadata={"kind": case["kind"]})
    threshold = get_settings().injection_block_threshold

    def task(*, item, **_):  # noqa: ANN001, ANN202
        return judge_request({"id": item.id, "kind": item.metadata.get("kind"), "expect": item.expected_output["verdict"],
                              **item.input}, threshold)

    async def correct(*, output, **_):  # noqa: ANN001, ANN202
        return Evaluation(name="guardrail_correct", value=1.0 if output["correct"] else 0.0, comment=output["reason"] or None)

    result = lf.run_experiment(name="guardrails-redteam", run_name=f"guardrails-{datetime.now(UTC):%Y%m%d-%H%M}",
                               data=lf.get_dataset(DATASET).items, task=task, evaluators=[correct], max_concurrency=4)
    lf.flush()
    return getattr(result, "experiment_url", None) or getattr(result, "dataset_run_url", None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--passages", type=int, default=200)
    parser.add_argument("--no-langfuse", action="store_true")
    args = parser.parse_args()
    setup_logging("WARNING")
    threshold = get_settings().injection_block_threshold
    data = json.loads((ROOT / "data" / "eval" / "guardrail_cases.json").read_text("utf-8"))

    # calibrate the semantic stage on the training set's benign requests only: the lowest
    # threshold above every benign similarity (+0.02 margin)
    from app.guardrails.semantic import detector

    benign_sims = [detector().score(redact(c["text"])[0])[0] for c in data["requests"] if c["expect"] == "pass"]
    semantic = round(max(benign_sims) + 0.02, 3)
    configured = get_settings().semantic_injection_threshold

    def rate(rows: list[dict], expect: str) -> float | None:
        group = [r for r in rows if r["expect"] == expect]
        return round(statistics.fmean(r["got"] == expect for r in group), 4) if group else None

    sets = {"training": data["requests"], "heldout_v1": data.get("heldout", []), "heldout_v2": data.get("heldout_v2", [])}
    stages = {}
    for name, cases in sets.items():
        pattern = [judge_request(c, threshold) for c in cases]
        both = [judge_request(c, threshold, semantic) for c in cases]
        stages[name] = {"n": len(cases),
                        "pattern_only": {"attack_block_rate": rate(pattern, "block"), "benign_pass_rate": rate(pattern, "pass")},
                        "two_stage": {"attack_block_rate": rate(both, "block"), "benign_pass_rate": rate(both, "pass")},
                        "misses": [r for r in both if not r["correct"]]}
    rows = [judge_request(c, threshold, semantic) for c in data["requests"]]
    by_kind: dict[str, dict] = {}
    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        by_kind[kind] = {"n": len(group), "correct": round(statistics.fmean(r["correct"] for r in group), 4)}
    attacks = [r for r in rows if r["expect"] == "block"]
    benign = [r for r in rows if r["expect"] == "pass"]

    pii_hits = []
    for case in data["pii"]:
        _, found = redact(case["text"])
        pii_hits.append(set(case["types"]) <= set(found))
    pii_clean = [not redact(text)[1] for text in data["pii_clean"]]

    clean, poisoned = passages(args.passages, data["injections"], threshold)
    metrics = {
        "attack_block_rate": round(statistics.fmean(r["got"] == "block" for r in attacks), 4),
        "benign_pass_rate": round(statistics.fmean(r["got"] == "pass" for r in benign), 4),
        "pii_recall": round(statistics.fmean(pii_hits), 4),
        "pii_clean_untouched": round(statistics.fmean(pii_clean), 4),
        "poisoned_passages_quarantined": round(statistics.fmean(p["quarantined"] for p in poisoned), 4),
        "clean_passages_kept": round(statistics.fmean(not c["quarantined"] for c in clean), 4),
    }
    out = {
        "created": datetime.now(UTC).isoformat(),
        "threshold": threshold,
        "semantic_threshold": {"calibrated": semantic, "configured": configured,
                               "max_benign_similarity": round(max(benign_sims), 4)},
        "counts": {"attacks": len(attacks), "benign": len(benign), "pii": len(pii_hits), "pii_clean": len(pii_clean),
                   "passages": len(clean)},
        "metrics": metrics,
        "stages": stages,
        "by_kind": by_kind,
        "failures": [r for r in rows if not r["correct"]]
        + [{"id": c["chunk_id"], "kind": "clean_passage", "signals": c["signals"]} for c in clean if c["quarantined"]]
        + [{"id": p["chunk_id"], "kind": "poisoned_passage", "attack": p["attack"]} for p in poisoned if not p["quarantined"]],
        "langfuse": None if args.no_langfuse else log_to_langfuse(rows),
    }
    folder = ROOT / "experiments" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"guardrail_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2), "utf-8")
    print(json.dumps({k: out[k] for k in ("counts", "metrics", "semantic_threshold", "stages")}, indent=2))
    for f in out["failures"]:
        print("FAIL", f)
    print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
