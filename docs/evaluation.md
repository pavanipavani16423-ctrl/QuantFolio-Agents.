# Evaluation results

All numbers below were produced by the scripts in `scripts/` on the committed data snapshot.
The raw results are in `experiments/results/`. Re-run them with:

```bash
uv run python scripts/eval_rag.py            # writes rag_eval_<ts>.json + Langfuse experiments
uv run python scripts/quantum_experiment.py  # writes quantum_eval_<ts>.json
```

## 1. Retrieval (hybrid RAG)

**Test set**: 47 questions with the chunk ids that answer them (`data/eval/golden_rag.json`):

* 20 *facts* questions ("What total revenue did Apple Inc. report for fiscal year 2025?"),
  generated from the XBRL facts documents;
* 9 *mandate* questions about the three investment policy statements;
* 18 *risk* questions, hand-written to paraphrase one specific 10-K risk-factor passage in
  plain words (e.g. "Why are fake medicines a risk for Pfizer?" for the passage on
  counterfeit products), so keyword search cannot simply match the filing's wording.

Each mode retrieves the top 6 over the **whole corpus** (2,119 chunks, no filters).

| Mode | hit rate@6 | recall@6 | MRR@6 | RAGAS ID context recall | RAGAS ID context precision | median latency |
|---|---|---|---|---|---|---|
| BM25 (keyword) | 83.0% | 80.9% | 0.739 | 0.809 | 0.145 | 7 ms |
| Dense (bge-small) | **93.6%** | **92.6%** | 0.795 | **0.926** | 0.174 | 14 ms |
| Hybrid (RRF) | 91.5% | 88.3% | 0.793 | 0.883 | 0.160 | 22 ms |
| Hybrid + rerank | 91.5% | 90.4% | **0.890** | 0.904 | 0.167 | 1.8 s |

Hit rate by question type:

| Mode | facts | mandate | risk (paraphrased) |
|---|---|---|---|
| BM25 | 100% | 100% | 55.6% |
| Dense | 95% | 100% | **88.9%** |
| Hybrid | 100% | 100% | 77.8% |
| Hybrid + rerank | 100% | 100% | 77.8% |

**What this shows, honestly:**

* Exact-token questions (company names, fiscal years, "Section 3.2") are easy for every
  mode except dense, which misses one facts question.
* On paraphrased questions, keyword search fails almost half the time; dense retrieval is
  much better. Plain RRF fusion inherits part of BM25's misses on those questions.
* The cross-encoder **reranker gives the best ranking** (MRR 0.89: the right passage is
  usually first), which matters most for the answer quality and for RAGAS context
  precision. It is also the slowest stage on a laptop CPU.
* ID-based context precision is low for every mode by construction: one or two relevant
  chunks among six retrieved.
* The default (`hybrid_rerank`) was chosen before this test set existed; the test set was
  not used to tune anything. A weighted fusion (more weight on dense) is an obvious next
  experiment.

Each mode is also a Langfuse experiment run on the dataset `quantfolio-rag-golden`, with
per-item scores, so individual misses can be inspected.

**LLM-judged metrics** (RAGAS faithfulness and factual correctness of generated answers)
are computed by the same script when an LLM key is configured. Per-run RAGAS scores
(faithfulness, answer relevancy, context precision and relevance, memo rubric) are attached
to every run's Langfuse trace.

## 2. Quantum (QAOA) vs exact search

Every client's real selection problem (prices of the training window), QAOA with
COBYLA (60 iterations, linear-ramp start), 2,048 shots, seed 7. "Gap" compares QAOA's best
valid sample with the exhaustive optimum.

| Client | qubits | pick k | design | p | gap to optimum | P(valid) | P(optimum) | approx. ratio | CX gates | QAOA time | exact time |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-101 | 20 | 10 | XY | 1 | **0%** (optimal) | 100% | 0.016% | 0.674 | 1,796 | 11.8 s | 0.36 s |
| C-101 | 20 | 10 | XY | 2 | **0%** (optimal) | 100% | 0.048% | 0.681 | 2,256 | 15.6 s | 0.36 s |
| C-101 | 20 | 10 | XY | 3 | **0%** (optimal) | 100% | 0.064% | 0.746 | 2,716 | 18.8 s | 0.36 s |
| C-101 | 20 | 10 | X (penalty) | 1 | 10.99% | 7% | 0.000% | 0.538 | 380 | 29.7 s | 0.36 s |
| C-101 | 20 | 10 | X (penalty) | 2 | 11.86% | 47% | 0.000% | 0.539 | 760 | 107.4 s | 0.36 s |
| C-101 | 20 | 10 | X (penalty) | 3 | 6.19% | 62% | 0.000% | 0.535 | 1,140 | 137.4 s | 0.36 s |
| C-102 | 18 | 8 | XY | 1 | 3.14% | 100% | 0.039% | 0.643 | 1,356 | 2.5 s | 0.05 s |
| C-102 | 18 | 8 | XY | 2 | **0%** (optimal) | 100% | 0.117% | 0.668 | 1,734 | 3.2 s | 0.05 s |
| C-102 | 18 | 8 | XY | 3 | **0%** (optimal) | 100% | 0.013% | 0.692 | 2,112 | 3.3 s | 0.05 s |
| C-102 | 18 | 8 | X (penalty) | 1 | 7.13% | 17% | 0.000% | 0.473 | 306 | 7.0 s | 0.05 s |
| C-102 | 18 | 8 | X (penalty) | 2 | 10.83% | 4% | 0.000% | 0.484 | 612 | 23.1 s | 0.05 s |
| C-102 | 18 | 8 | X (penalty) | 3 | 12.62% | 2% | 0.000% | 0.507 | 918 | 32.8 s | 0.05 s |
| C-103 | 19 | 12 | XY | 1 | 0.08% | 100% | 0.024% | 0.684 | 1,810 | 5.7 s | 0.07 s |
| C-103 | 19 | 12 | XY | 2 | **0%** (optimal) | 100% | 0.043% | 0.701 | 2,228 | 5.6 s | 0.07 s |
| C-103 | 19 | 12 | XY | 3 | 0.08% | 100% | 0.014% | 0.724 | 2,646 | 5.4 s | 0.07 s |
| C-103 | 19 | 12 | X (penalty) | 1 | 1.46% | 41% | 0.001% | 0.502 | 342 | 25.2 s | 0.07 s |
| C-103 | 19 | 12 | X (penalty) | 2 | **0%** (optimal) | 41% | 0.001% | 0.502 | 684 | 42.8 s | 0.07 s |
| C-103 | 19 | 12 | X (penalty) | 3 | 3.83% | 15% | 0.000% | 0.494 | 1,026 | 61.4 s | 0.07 s |

Summary:

| Design | runs | optimum found | mean gap | mean P(valid) | mean approx. ratio | mean time |
|---|---|---|---|---|---|---|
| XY mixer + Dicke start | 9 | **6/9** (3/3 at p = 2, the default) | 0.37% | **100%** | 0.691 | 8.0 s |
| X mixer + penalty | 9 | 1/9 | 7.21% | 26% | 0.508 | 51.9 s |

**What this shows, honestly:**

* Building the constraint into the circuit matters more than depth. The XY design never
  wastes a shot on an invalid portfolio and finds the optimum in most runs; the
  penalty-based standard QAOA produces mostly invalid bitstrings (26% valid on average) and
  falls up to 12.6% short (7.2% on average).
* The probability of measuring the optimum directly is tiny (at most 0.12%). QAOA finds the
  optimum because the best of 2,048 measured portfolios is kept. The approximation ratio
  (0.64-0.75) shows the state is biased toward good portfolios, not concentrated on the best.
* Deeper is not always better at a fixed 60-iteration budget (C-103, p = 3).
* One round of classical 1-swap local search (the hybrid method) reaches the optimum from
  every QAOA answer in these cases.
* Exhaustive classical search solves each instance in 0.05-0.4 s; QAOA on the simulator takes
  2-140 s. **No quantum advantage is observed or claimed.** The circuits (1,300-2,700 CX
  gates for XY) are also too deep for today's noisy hardware without error mitigation.

