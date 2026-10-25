# Evaluation results

All numbers below were produced by the scripts in `scripts/` on the committed data snapshot.
The raw results are in `experiments/results/`. Re-run them with:

```bash
uv run python scripts/eval_rag.py            # writes rag_eval_<ts>.json + Langfuse experiments
uv run python scripts/quantum_experiment.py  # writes quantum_eval_<ts>.json
```

## 1. Retrieval (hybrid RAG)

**Test set**: 78 questions with the chunk ids that answer them (`data/eval/golden_rag.json`):

* 38 *facts* questions ("What total revenue did Apple Inc. report for fiscal year 2025?"),
  generated from the US XBRL and Indian reported-financials documents;
* 12 *mandate* questions about the four investment policy statements;
* 18 US *risk* questions, hand-written to paraphrase one specific 10-K risk-factor passage in
  plain words (e.g. "Why are fake medicines a risk for Pfizer?" for the passage on
  counterfeit products), so keyword search cannot simply match the filing's wording;
* 10 India *risk* questions written the same way about annual-report MD&A, risk and BRSR
  passages (e.g. "How many steps are in Asian Paints' process for handling risks?").

Each mode retrieves the top 6 over the **whole corpus** (4,585 chunks, both markets, no
filters).

| Mode | hit rate@6 | recall@6 | MRR@6 | RAGAS ID context recall | RAGAS ID context precision | median latency |
|---|---|---|---|---|---|---|
| BM25 (keyword) | 84.6% | 82.7% | 0.759 | 0.827 | 0.143 | 9 ms |
| Dense (bge-small) | **96.2%** | **95.5%** | 0.822 | **0.955** | 0.171 | 10 ms |
| Hybrid (RRF) | 94.9% | 93.0% | 0.836 | 0.930 | 0.162 | 19 ms |
| Hybrid + rerank | 94.9% | 94.2% | **0.924** | 0.942 | 0.167 | 1.3 s |

Hit rate by question type:

| Mode | facts | mandate | US risk (paraphrased) | India risk (paraphrased) |
|---|---|---|---|---|
| BM25 | 100% | 100% | 55.6% | 60% |
| Dense | 97.4% | 100% | **88.9%** | **100%** |
| Hybrid | 100% | 100% | 77.8% | **100%** |
| Hybrid + rerank | 100% | 100% | 77.8% | **100%** |

**What this shows, honestly:**

* Exact-token questions (company names, fiscal years, "Section 3.2") are easy for every
  mode except dense, which misses one facts question.
* On paraphrased questions, keyword search fails almost half the time; dense retrieval is
  much better. Plain RRF fusion inherits part of BM25's misses on the US questions.
* The cross-encoder **reranker gives the best ranking** (MRR 0.92: the right passage is
  usually first), which matters most for the answer quality and for RAGAS context
  precision. It is also the slowest stage on a laptop CPU.
* Adding the Indian corpus more than doubled the index without hurting the US questions.
* ID-based context precision is low for every mode by construction: one or two relevant
  chunks among six retrieved.
* The default (`hybrid_rerank`) was chosen before this test set existed; the test set was
  not used to tune anything. A weighted fusion (more weight on dense) is an obvious next
  experiment.

Each mode is also a Langfuse experiment run on the dataset `quantfolio-rag-golden`, with
per-item scores, so individual misses can be inspected.

**LLM-judged metrics** (RAGAS, judge `qwen/qwen3.8-27b` on Groq): the research model
(`gpt-oss-120b`) answered 8 risk questions (4 US, 4 India) from the `hybrid_rerank` top 6.

| Metric | score | items |
|---|---|---|
| Faithfulness (claims supported by the retrieved passages) | **0.79** | 8 |
| Factual correctness (F1 of claims vs the reference passage) | 0.16 | 7 (1 judge error) |

Factual correctness is low by construction here: the reference is the whole filing passage,
while the answer is two to four sentences, so the recall half of the F1 penalises everything
the answer leaves out. Faithfulness is the meaningful number for grounding; a short
hand-written reference answer per question would make factual correctness informative. Per-run RAGAS scores
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
| C-201 (India) | 17 | 8 | XY | 1 | 10.31% | 100% | 0.018% | 0.647 | 1,244 | 1.2 s | 0.03 s |
| C-201 (India) | 17 | 8 | XY | 2 | 9.87% | 100% | 0.020% | 0.657 | 1,584 | 1.4 s | 0.03 s |
| C-201 (India) | 17 | 8 | XY | 3 | 9.87% | 100% | 0.012% | 0.658 | 1,924 | 1.6 s | 0.03 s |
| C-201 (India) | 17 | 8 | X (penalty) | 1 | 15.30% | 19% | 0.001% | 0.492 | 272 | 3.0 s | 0.03 s |
| C-201 (India) | 17 | 8 | X (penalty) | 2 | 74.31% | 0% | 0.000% | 0.407 | 544 | 9.0 s | 0.03 s |
| C-201 (India) | 17 | 8 | X (penalty) | 3 | 22.51% | 4% | 0.000% | 0.486 | 816 | 13.0 s | 0.03 s |

Summary:

| Design | runs | optimum found | mean gap | mean P(valid) | mean approx. ratio | mean time |
|---|---|---|---|---|---|---|
| XY mixer + Dicke start | 12 | **6/12** (3/4 at p = 2, the default) | 2.78% | **100%** | 0.681 | 6.3 s |
| X mixer + penalty | 12 | 1/12 | 14.75% | 22% | 0.497 | 41.0 s |

**What this shows, honestly:**

* Building the constraint into the circuit matters more than depth. The XY design never
  wastes a shot on an invalid portfolio and finds the optimum in half the runs (3 of 4 at the
  default depth); the
  penalty-based standard QAOA produces mostly invalid bitstrings (22% valid on average) and
  falls up to 74% short (15% on average).
* The probability of measuring the optimum directly is tiny (at most 0.12%). QAOA finds the
  optimum because the best of 2,048 measured portfolios is kept. The approximation ratio
  (0.64-0.75) shows the state is biased toward good portfolios, not concentrated on the best.
* Deeper is not always better at a fixed 60-iteration budget (C-103, p = 3).
* The Indian mandate (C-201, 17 qubits) is the hardest case: no QAOA run hit the optimum
  (best gap 9.9%, XY at p = 2 and 3), while the penalty design fell 15-74% short with
  0.4-19% valid samples.
* One round of classical 1-swap local search (the hybrid method) reaches the optimum from
  every QAOA answer in all 24 cases.
* Exhaustive classical search solves each instance in 0.03-0.4 s; QAOA on the simulator takes
  1-140 s. **No quantum advantage is observed or claimed.** The circuits (1,200-2,700 CX
  gates for XY) are also too deep for today's noisy hardware without error mitigation.

