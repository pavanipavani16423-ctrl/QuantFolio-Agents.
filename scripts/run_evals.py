"""The evaluation harness: run every offline evaluation and write one report.

    uv run python scripts/run_evals.py                 # guardrails + citations + RAG (+ LLM-judged items if a key is set)
    uv run python scripts/run_evals.py --tune          # also re-run the RAG configuration sweep (slow: re-embeds the corpus)
    uv run python scripts/run_evals.py --report-only   # just rebuild the report from the latest results

Each evaluation writes its own JSON to experiments/results/ (and a Langfuse dataset +
experiment when Langfuse is configured). This script runs them in order and then writes
experiments/results/REPORT.md from the latest file of each kind, so the numbers in the README
can always be traced back to a result file.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "experiments" / "results"


def run(args: list[str]) -> None:
    print("\n$", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def latest(kind: str) -> dict | None:
    files = sorted(RESULTS.glob(f"{kind}_*.json"))
    return json.loads(files[-1].read_text("utf-8")) | {"_file": files[-1].name} if files else None


def pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.1%}"


def report() -> str:
    lines = [f"# Evaluation report\n\nGenerated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `scripts/run_evals.py`.\n"]
    rag = latest("rag_eval")
    if rag:
        k = rag["k"]
        lines += [f"## Retrieval ({rag['dataset']['items']} labelled questions, top {k}) - `{rag['_file']}`\n",
                  "| Mode | hit rate | MRR | recall | median latency |", "|---|---|---|---|---|"]
        for mode, m in rag["modes"].items():
            lines.append(f"| {mode} | {pct(m[f'hit_rate@{k}'])} | {m[f'mrr@{k}']:.3f} | {pct(m[f'recall@{k}'])} | {m['latency_ms']:.0f} ms |")
        llm = (rag.get("llm") or {}).get("metrics")
        if llm:
            for mode, m in llm.items():
                lines.append(f"\nLLM-judged ({rag['llm']['judge']}, {mode}): "
                             + ", ".join(f"{name} {v:.2f}" for name, v in m.items() if v is not None))
        lines.append("")
    tune = latest("rag_tuning")
    if tune:
        from app.config import get_settings

        b, s = tune["best"], get_settings()
        lines += [f"## RAG configuration sweep - `{tune['_file']}`\n",
                  f"Sweep's best by hit rate: {b['size'][0]}-character chunks, `{b['model']}` (query instruction: "
                  f"{b['prefix']}), `{b['reranker']}`, {b['candidates']} candidates, rerank top {b['rerank_top']}, "
                  f"k = {b['k']}.\n",
                  f"In use (`app/config.py`, see the comment there for why): {s.chunk_target_chars}-character "
                  f"chunks, `{s.embedding_model}` (query instruction: {s.embedding_query_prefix}), "
                  f"`{s.reranker_model}`, {s.rag_candidates} candidates, rerank top {s.rag_rerank_top}, "
                  f"k = {s.rag_top_k}.\n"]
    guard = latest("guardrail_eval")
    if guard:
        lines += [f"## Guardrails red team - `{guard['_file']}`\n", "| Metric | Value |", "|---|---|"]
        lines += [f"| {k} | {pct(v)} |" for k, v in guard["metrics"].items()]
        lines += ["", "| Test set | cases | attacks stopped (patterns) | attacks stopped (two-stage) | benign allowed |",
                  "|---|---|---|---|---|"]
        for name, s in guard.get("stages", {}).items():
            lines.append(f"| {name} | {s['n']} | {pct(s['pattern_only']['attack_block_rate'])} | "
                         f"{pct(s['two_stage']['attack_block_rate'])} | {pct(s['two_stage']['benign_pass_rate'])} |")
        lines.append("")
    cal = latest("citation_calibration")
    if cal:
        lines += [f"## Citation gate calibration - `{cal['_file']}`\n",
                  f"Reranker `{cal['reranker']}`, {cal['pairs']} pairs: threshold {cal['threshold']}, supported claims "
                  f"accepted {pct(cal['supported_accepted'])}, hard negatives rejected {pct(cal['hard_negatives_rejected'])}, "
                  f"easy negatives rejected {pct(cal['easy_negatives_rejected'])}.\n"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--llm-items", type=int, default=8)
    args = parser.parse_args()
    if not args.report_only:
        if args.tune:
            run(["scripts/tune_rag.py"])
        run(["scripts/eval_guardrails.py"])
        run(["scripts/calibrate_citations.py"])
        run(["scripts/eval_rag.py", "--llm-items", str(args.llm_items)])
    path = RESULTS / "REPORT.md"
    path.write_text(report(), "utf-8")
    print(f"\nwrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
