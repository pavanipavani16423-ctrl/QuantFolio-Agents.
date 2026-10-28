# Evaluation report

Generated 2026-10-28 02:35 UTC by `scripts/run_evals.py`.

## Retrieval (78 labelled questions, top 6) - `rag_eval_20261028T023433Z.json`

| Mode | hit rate | MRR | recall | median latency |
|---|---|---|---|---|
| bm25 | 85.9% | 0.743 | 85.9% | 8 ms |
| dense | 94.9% | 0.808 | 94.9% | 15 ms |
| hybrid | 92.3% | 0.817 | 92.3% | 42 ms |
| hybrid_rerank | 94.9% | 0.901 | 94.9% | 3808 ms |

LLM-judged (groq:qwen/qwen3.8-27b, hybrid_rerank): ragas_faithfulness 0.92, ragas_factual_correctness 0.19

## RAG configuration sweep - `rag_tuning_20261027T065910Z.json`

Sweep's best by hit rate: 1100-character chunks, `BAAI/bge-small-en-v1.5` (query instruction: False), `Xenova/ms-marco-MiniLM-L-12-v2`, 20 candidates, rerank top 20, k = 6.

In use (`app/config.py`, see the comment there for why): 1100-character chunks, `BAAI/bge-small-en-v1.5` (query instruction: False), `Xenova/ms-marco-MiniLM-L-6-v2`, 40 candidates, rerank top 20, k = 6.

## Guardrails red team - `guardrail_eval_20261028T020629Z.json`

| Metric | Value |
|---|---|
| attack_block_rate | 100.0% |
| benign_pass_rate | 100.0% |
| pii_recall | 100.0% |
| pii_clean_untouched | 100.0% |
| poisoned_passages_quarantined | 100.0% |
| clean_passages_kept | 100.0% |

| Test set | cases | attacks stopped (patterns) | attacks stopped (two-stage) | benign allowed |
|---|---|---|---|---|
| training | 50 | 100.0% | 100.0% | 100.0% |
| heldout_v1 | 15 | 60.0% | 70.0% | 80.0% |
| heldout_v2 | 15 | 50.0% | 87.5% | 100.0% |

## Citation gate calibration - `citation_calibration_20261028T020749Z.json`

Reranker `Xenova/ms-marco-MiniLM-L-6-v2`, 279 pairs: threshold 1.24, supported claims accepted 95.0%, hard negatives rejected 94.3%, easy negatives rejected 100.0%.
