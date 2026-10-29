# Evaluation results

Every number here was produced by a script in `scripts/` on the committed data snapshot. The raw
results are in `experiments/results/`, and `REPORT.md` there sums up the latest of each.

```bash
uv run python scripts/run_evals.py          # guardrails, citation gate, retrieval -> REPORT.md
uv run python scripts/run_evals.py --tune   # + the RAG configuration sweep (about an hour on CPU)
uv run pytest                               # 96 tests, offline
uv run --with pgserver python scripts/test_postgres.py   # the same tests on Postgres
```

## 1. Retrieval (hybrid RAG)

**Test set** (`scripts/eval_rag.py`, also a Langfuse dataset `quantfolio-rag-golden`): 78
questions.

| Kind | Questions | How they are made |
|---|---|---|
| facts | 38 | "What total revenue did Apple Inc. report for fiscal year 2025?", from the US XBRL and Indian reported-financials documents |
| mandate | 12 | questions about the four demo investment policies |
| US risk | 18 | hand-written to reword one 10-K risk-factor passage ("Why are fake medicines a risk for Pfizer?" for the passage on counterfeit products), so keyword search cannot just match the filing's words |
| India risk | 10 | the same, for annual-report MD&A, risk and BRSR passages |

The answer passage is found by an anchor phrase from its text, not by a chunk id, so the set
stays valid when the chunking changes. Each mode retrieves the top 6 over the whole corpus
(2,900 chunks, both markets, no filters).

| Mode | hit rate@6 | MRR@6 | facts | mandate | US risk | India risk | RAGAS ID context recall |
|---|---|---|---|---|---|---|---|
| BM25 (keyword) | 85.9% | 0.743 | 100% | 100% | 44.4% | 90% | 0.859 |
| Dense (bge-small) | 94.9% | 0.808 | 97.4% | 100% | **83.3%** | 100% | 0.949 |
| Hybrid (RRF) | 92.3% | 0.817 | 100% | 100% | 66.7% | 100% | 0.923 |
| **Hybrid + rerank** | **94.9%** | **0.901** | 100% | 100% | 77.8% | **100%** | 0.949 |

**LLM-judged** (RAGAS, judge `qwen/qwen3.8-27b` on Groq): the research model answered 8 risk
questions (4 US, 4 India) from the hybrid + rerank top 6.
* **Faithfulness** (claims supported by the passages): **0.92**.
* Factual correctness: 0.19. This is low by construction: the reference is the whole passage,
  while the answer is two to four sentences.

**What this shows:**
* Exact-token questions (company names, fiscal years, "Section 3.2") are easy for every mode.
* On reworded risk questions, keyword search fails most often and dense search finds the most.
  Plain RRF inherits part of BM25's misses.
* The cross-encoder reranker gives the best ranking: MRR 0.90, so the right passage is usually
  first. That matters most for the answer, because the model reads the top passages first.
* Median latency of hybrid + rerank is about 1.4 s on an idle laptop CPU. (The latest run shows
  3.8 s because it shared the CPU with other jobs.)

## 2. A data-quality fix found by testing a real client

Testing an added client end to end, the research report covered TCS with one passage and HDFC
Bank with none. The trace showed three causes:
* The intake model had dropped HDFC Bank from its ticker list.
* One search over three companies let one of them take four of six passages.
* The chunker cut the Indian reports into fragments.

The Indian reports are PDF text, with a line break in the middle of most sentences. Any short
line starting with a capital letter was taken for a heading, and chunks never cross a heading.
So **18% of all chunks (826 of 4,585) were fragments under 120 characters** ("in building the
Nilaya brand as a top"). HDFC Bank's best BRSR "passage" was its "Source: …" line.

The fixes:
* **The chunker reflows PDF text** into sentences. A line is a heading only if it stands alone.
  Chunks under 300 characters are merged into a neighbour, and source lines and page numbers are
  dropped.
* **One filtered search per company**, then the passages are merged.
* **The intake model's ticker list is merged with a name matcher.**
* **The extractive fallback quotes whole sentences only.**

| | before | after |
|---|---|---|
| chunks | 4,585 | 2,900 |
| chunks under 120 characters | 826 (18%) | 0 |
| hit rate@6, hybrid + rerank | 94.9% | 94.9% |
| MRR@6, hybrid + rerank | 0.924 | 0.901 |
| RAGAS faithfulness (8 answers) | 0.79 | **0.92** |
| passages for TCS / HDFC Bank / Hindustan Unilever, live question | 1 / 1 / 4 (one a source line) | 2 / 2 / 2 |
| the model's first draft passes the checks (that question) | no, extractive fallback | yes |

The answers became more grounded, and retrieval found the answer passage as often as before.
Ranking moved by about two questions of 78 (the answer second instead of first), which is
within noise for this set. Each fix has a regression test.

## 3. RAG configuration sweep

`scripts/tune_rag.py`, a staged sweep on the 78 questions (relevance by text anchors, so
different chunkings compare fairly). Each stage starts from the best of the previous one. It
ran before the chunking fix of section 2, which changes the Indian chunk boundaries but not the
settings compared here.

| Stage | Option | hit rate | MRR | latency |
|---|---|---|---|---|
| A. chunk size (hybrid + rerank) | 500 characters (6,811 chunks) | 92.3% | 0.892 | 1.4 s |
| | 800 (5,230) | 92.3% | 0.902 | 1.8 s |
| | **1100 (4,585)** | **94.9%** | **0.934** | 2.2 s |
| B. embedding (dense alone / hybrid + rerank) | **bge-small** | 96.2% / 94.9% | 0.829 / **0.934** | |
| | bge-small + query instruction | 96.2% / 94.9% | 0.847 / 0.934 | |
| | bge-base | 97.4% / 94.9% | 0.850 / 0.934 | |
| | bge-base + query instruction | 94.9% / 94.9% | 0.846 / 0.934 | |
| C. reranker | **MiniLM-L-6** | 94.9% | **0.934** | **1.4 s** |
| | MiniLM-L-12 | 96.2% | 0.923 | 3.2 s |
| | jina-reranker-v1-turbo | 96.2% | 0.921 | 1.6 s |
| | bge-reranker-v2-m3 (int8) | 94.9% | 0.912 | 20.8 s |
| D. depth (with MiniLM-L-12) | candidates 20/40 × rerank 10/20/30, k 4/6/8 | 94.9-97.4% | 0.921-0.927 | 1.3-5.7 s |

**Decisions:**
* 1100-character chunks.
* bge-small without the query instruction. The bigger model helps dense search alone, but not
  after reranking.
* **MiniLM-L-6.** The sweep's automatic pick was MiniLM-L-12 (one more question found), but it
  ranks worse and takes twice as long. One question in 78 is noise.
* 40 candidates, rerank depth 20, top 6. Top 8 finds 97.4%, but it means 30% more text in every
  prompt.

## 4. Guardrails red team

`scripts/eval_guardrails.py`, also the Langfuse dataset `quantfolio-guardrails-redteam`. The
attacks are split into a set the rules were written against and two held-out sets written
afterwards. The second held-out set was written before the semantic stage was calibrated.

| Test set | cases | attacks stopped, patterns only | attacks stopped, two stages | normal requests allowed |
|---|---|---|---|---|
| training | 50 | 100% | 100% | 100% |
| held-out 1 | 15 | 60% | 70% | 80% |
| held-out 2 | 15 | 50% | **87.5%** | 100% |

* **Personal data:** 100% of 8 cases redacted (email, phone, PAN, Aadhaar, card with Luhn, SSN,
  IFSC, account number); 5 clean texts left untouched.
* **Poisoned documents:** an instruction planted into 200 real report passages. 100% were set
  aside, and 100% of the clean versions were kept.
* **Semantic stage:** embedding similarity to 13 generic attack intents. The threshold is 0.706:
  the highest similarity of any normal request (0.686) plus a margin.

**What this shows:** the rules are perfect on what they were written for and clearly weaker on
unseen attacks. The meaning-based stage closes much of that gap. That is why the actions do not
depend on the guardrails alone: orders need a signed approval bound to the exact orders, and the
broker enforces hard limits.

## 5. Citation gate

`scripts/calibrate_citations.py`. Every sentence with a citation [n] in a research answer is
scored against the passage it cites by the cross-encoder. The test pairs:
* supported: a sentence from the passage;
* hard negative: a sentence from another passage of the same company;
* easy negative: a sentence from another company.

279 pairs. The threshold is the 5th percentile of supported scores: **1.24**.

| | share |
|---|---|
| supported claims accepted | 95.0% |
| hard negatives rejected | 94.3% |
| easy negatives rejected | 100% |

A research answer is blocked when more than a third of its cited claims fail. It is then
rewritten once with the findings as feedback, and if it fails again it falls back to quoting
the passages.

## 6. Agents and the whole system

* **Rule extraction:** the compliance agent reads every rule of all four demo policies correctly
  (`output_rule_extraction_accuracy` = 1.0). For an added client, a test checks the round trip:
  form, then policy document, then the same rules back.
* **Every recommended portfolio passes every rule**, and excluded sectors and companies never
  appear (end-to-end tests on all clients).
* **96 tests**, each run on SQLite and on Postgres. They cover the full HTTP flow:
  * guardrails at every layer;
  * pause for approval, then approve, change and reject;
  * signed single-use approvals, including concurrent approvals;
  * broker limits;
  * memory and poisoned notes;
  * the audit chain;
  * adding and removing a client;
  * the A2A fallback.

## 7. Speed: how structured output is requested

Every agent asks the model for a typed object (the intake task, the research report, the policy
rules, the memo). It was asked through a **tool call**, and sometimes the model named the tool
wrongly, for example `memo` instead of `Memo`. The provider rejected that call, and the retry cost
10–20 seconds. The comparison below used Groq's **Structured Output API** (`json_schema`), where
the provider holds the output to the schema. Both methods ran the same GreenLeaf request 3 times,
on live Groq, with the research cache and background judging off.

| | tool call | `json_schema` |
|---|---|---|
| failed model calls | 5 of 17 | **0 of 12** |
| median time to the decision box | 75.3 s | **37.2 s** |
| median report-writer time | 17.3 s | **6.2 s** |
| answers from the model (not the rule-based fallback) | 6 of 6 | 6 of 6 |

`json_schema` is now the default on Groq and OpenAI (`LLM_STRUCTURED_METHOD` overrides it);
plain JSON mode stays as the fallback.

## 8. What the background RAGAS judging costs

RAGAS runs **after** the decision box appears, so the advisor never waits for it. Measured on the
GreenLeaf run: the plan was ready at 51 s, and the judge's scores arrived at 206 s (about 155 s of
background work, about 10 judge calls on Groq).

| Cost | Effect | What the design does about it |
|---|---|---|
| Waiting time | none for the advisor | runs off the request path; the Checks tab fills in later |
| Model tokens and rate limits | about 10 judge calls per run | a different model from the agents (separate per-model limits); `ONLINE_EVALUATION_SAMPLE_RATE` judges a stable share of runs (0.2 = 1 in 5) |
| Memory | the RAGAS libraries add about 70 MB | loaded only when a run is judged; off on a 512 MB server |
| CPU | embeddings for answer relevancy | small next to the agents |

The deterministic checks (citations, numbers against the facts, the client's rules, the
guardrails) run on every run in milliseconds. The offline evaluation (sections 1–5) measures
quality on fixed datasets. That is the usual split: cheap checks on all traffic, an LLM judge on
a sample.

## 9. Memory: fitting a whole plan in 512 MB

The free Render plan has 512 MB without swap and 0.1 CPU. In CI, `scripts/check_free_plan.py` runs
a whole plan (the largest client, 184,756 portfolio candidates) in the Docker image. Anonymous
memory (what the kernel cannot reclaim) at the plan's peak:

| Change | Plan peak |
|---|---|
| starting point (full settings) | killed at 512 MB (585 MiB unlimited) |
| exact search in blocks of 20,000 subsets (same answers on 40 random problems) | 102 → 14 MB for the search itself |
| int8 reranker, lighter ONNX optimisation, one plan at a time | 554 MiB |
| glibc allocator thresholds fixed (`MALLOC_MMAP_THRESHOLD_`, `MALLOC_TRIM_THRESHOLD_`) | **386 MiB** |
| plus one tokenizer thread instead of one per host core | **366 MiB** |
| at the free plan's limits (512 MB, 0.1 CPU) | passes: peak 428 MiB, plan 74 s |

The biggest win was not in the app. After the first large buffer is freed, glibc raises its
threshold and keeps later large buffers (ONNX tensors, numpy arrays) in its own heap, so each new
size of query added memory that was never returned. The first query embedding cost +81 MB on
Linux and almost nothing on Windows, which pointed to the allocator. With the thresholds fixed,
the same query costs +1 MB.

## What is not measured yet

* Factual correctness against short hand-written reference answers (the current reference is the
  whole passage).
* Multi-turn and adversarial conversations beyond single requests.
* Portfolio quality beyond the short out-of-sample backtest (no transaction costs).
