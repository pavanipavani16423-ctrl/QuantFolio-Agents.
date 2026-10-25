"""Quantum experiment: QAOA vs the exact optimum on each client's real selection problem.

For every client mandate (18-20 assets, choose exactly 8-12) and every configuration
(mixer x / xy, depth p), run QAOA on the simulator and compare its best feasible sample with
exhaustive search. Also reports what one round of classical 1-swap local search adds (the
hybrid method).

    uv run python scripts/quantum_experiment.py [--reps 1 2 3] [--mixers xy x] [--maxiter 60]
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.optimizer import build_problem  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.data import store  # noqa: E402
from app.data.universe import BENCHMARK, TICKERS  # noqa: E402
from app.quant.portfolio import local_search, select_exact, selection_problem  # noqa: E402
from app.quant.stats import market_stats  # noqa: E402
from app.quantum.qaoa_solver import QAOAConfig, run_qaoa  # noqa: E402
from app.schemas import MandateRules  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--mixers", nargs="+", default=["xy", "x"])
    parser.add_argument("--maxiter", type=int, default=60)
    parser.add_argument("--shots", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    s = get_settings()
    truth = json.loads((ROOT / "data" / "eval" / "mandate_truth.json").read_text())
    stats = market_stats(store.prices(), list(TICKERS), BENCHMARK, s.train_start, s.train_end).to_dict()

    cases = []
    for client in ("C-101", "C-102", "C-103"):
        rules = MandateRules(client_id=client, **truth[client])
        p = build_problem(stats, rules)
        sp = selection_problem(p["tickers"], p["sectors"], p["mu"], p["cov"], p["k"],
                               p["risk_aversion"], p["max_sector_weight"])
        exact = select_exact(sp)
        for mixer in args.mixers:
            for reps in args.reps:
                started = time.perf_counter()
                res = run_qaoa(sp.qubo(with_penalty=(mixer == "x")), QAOAConfig(
                    reps=reps, maxiter=args.maxiter, shots=args.shots, mixer=mixer,
                    hamming_weight=sp.k, seed=args.seed, top_k=128))
                secs = time.perf_counter() - started
                feasible = [x for x in res.samples if sp.feasible(x.bits)]
                if feasible:
                    u = sp.utility(feasible[0].bits)
                    start_bits = feasible[0].bits
                else:
                    u = float("nan")
                    start_bits = None
                gap = max(0.0, (exact.utility - u) / abs(exact.utility)) if feasible else 1.0
                ls_gap = 1.0
                if start_bits is not None:
                    refined, _ = local_search(sp, start_bits)
                    ls_gap = max(0.0, (exact.utility - sp.utility(refined)) / abs(exact.utility))
                case = {
                    "client": client, "n": sp.n, "k": sp.k, "mixer": mixer, "reps": reps,
                    "gap": round(gap, 6), "found_optimum": gap <= 1e-9,
                    "approximation_ratio": res.feasible_approximation_ratio,
                    "optimal_probability": res.optimal_probability,
                    "feasible_probability": res.feasible_probability,
                    "feasible_sample_fraction": res.feasible_sample_fraction,
                    "circuit_depth": res.circuit_depth, "two_qubit_gates": res.two_qubit_gates,
                    "iterations": res.iterations, "seconds": round(secs, 2),
                    "classical_seconds": round(exact.seconds, 3),
                    "after_local_search_gap": round(ls_gap, 6),
                }
                cases.append(case)
                print(f"{client} n={sp.n} k={sp.k} {mixer} p={reps}: gap {gap:.2%} AR {res.feasible_approximation_ratio:.3f} "
                      f"P(opt) {res.optimal_probability:.4f} P(feas) {res.feasible_probability:.3f} "
                      f"depth {res.circuit_depth} cx {res.two_qubit_gates} {secs:.1f}s (exact {exact.seconds:.2f}s)", flush=True)

    summary = {}
    for mixer in args.mixers:
        rows = [c for c in cases if c["mixer"] == mixer]
        summary[mixer] = {
            "runs": len(rows),
            "found_optimum": sum(c["found_optimum"] for c in rows),
            "mean_gap": round(sum(c["gap"] for c in rows) / len(rows), 6),
            "mean_feasible_probability": round(sum(c["feasible_probability"] for c in rows) / len(rows), 4),
            "mean_approximation_ratio": round(sum(c["approximation_ratio"] or 0 for c in rows) / len(rows), 4),
            "mean_seconds": round(sum(c["seconds"] for c in rows) / len(rows), 2),
        }
    xy, x = summary.get("xy"), summary.get("x")
    notes = [
        "Each stock is one qubit; the problem is exactly the one the agents solve for each client (training window prices).",
        "The quantum answer is the best valid bitstring among the measured samples; 'gap' is its utility shortfall vs exhaustive search.",
        "Simulated on a laptop CPU: quantum time is simulation time, not hardware time. Exhaustive search is much faster at this size.",
    ]
    if xy and x:
        notes.insert(0, f"XY mixer: optimum found in {xy['found_optimum']}/{xy['runs']} runs, every sample valid "
                        f"(P(valid) {xy['mean_feasible_probability']:.0%}). Standard X mixer: optimum in "
                        f"{x['found_optimum']}/{x['runs']} runs, P(valid) {x['mean_feasible_probability']:.0%}, mean gap {x['mean_gap']:.1%}.")
    notes.append("One round of classical 1-swap local search (the hybrid method) closes any remaining gap in these cases."
                 if all(c["after_local_search_gap"] <= 1e-9 for c in cases)
                 else "Classical local search does not always close the gap (see 'after swaps').")
    out = {"created": datetime.now(UTC).isoformat(), "config": vars(args), "cases": cases,
           "summary": summary, "notes": notes}
    folder = ROOT / "experiments" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"quantum_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2), "utf-8")
    print("wrote", path.relative_to(ROOT))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
