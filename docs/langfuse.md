# Langfuse: tracing, scores and experiments

QuantFolio Agents sends three kinds of data to Langfuse (Python SDK v5, OpenTelemetry based):

1. **One trace per run**, with one clearly numbered section per agent step.
2. **Scores on every trace**: RAGAS quality metrics, deterministic checks, portfolio
   numbers, guardrail and memory counters, and the human decision.
3. **Datasets with experiment runs**: the labelled RAG test set (one run per retrieval mode)
   and the guardrail red-team set.

Personal data is masked out of every input, output and metadata field before export (the
client's `mask` function, `app/observability/tracing.py`), and the approval token never appears
in tool-call previews.

Tracing is off until `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set (`.env`); the
code path is the same either way.

## 1. The trace of a run

Open a run in the web UI and click **See every step in Langfuse**, or open *Tracing → Traces*
in Langfuse and filter by tag (client id, profile, `llm:groq`, `start`/`resume`).

```text
portfolio-run                                          chain    (user = client, session = client-<id>)
├── 01 Input guardrails - personal data, prompt injection, scope policy   guardrail  WARNING if stopped
├── 02 Intake agent - understand the request, recall memory               agent
│   └── llm.intake                                     generation  model, prompt, tokens, latency
├── 03 Research agent - hybrid RAG with retrieval and output guardrails   agent
│   ├── rag.search: <question>                         retriever   BM25 / dense / fused / reranked ids
│   │   └── mcp.research.search_documents              tool
│   ├── llm.research_answer                            generation
│   └── llm.research_answer_revision                   generation  only after a failed check
├── 04 Risk agent (A2A) - market risk profile          agent
│   └── A2A risk-agent: market-risk-profile            agent       <- span created by the remote service
├── 05 Compliance agent (A2A) - read the client mandate
│   └── A2A compliance-agent: extract-mandate-rules    agent
│       ├── mcp.research.search_documents  (x7)        tool
│       └── llm.compliance_extract_rules               generation
├── 06 Portfolio optimizer - exact search vs baseline  agent
│   ├── mcp.optimizer.select_stocks                    tool
│   └── mcp.optimizer.optimize_portfolio_weights (x2)  tool
├── 07 Backtest - out-of-sample performance            tool
├── 08 Compliance and risk check (A2A)                 guardrail   WARNING level if a rule fails
├── 09 Report writer - memo with output guardrails     agent       (+ llm.report_writer_revision)
├── 10 Quality evaluation - RAGAS and checks           evaluator   fast deterministic checks
│   └── 10b RAGAS quality scoring (background)         evaluator   runs while the advisor reviews
│       └── judge.<RAGAS prompt>  (several)            generation  the judge model's own calls
└── 11 Trade proposal - paper broker with order limits tool
portfolio-run  (resume, same trace id, after the human decision)
├── 12 Human approval - signed approval token          span        "change" -> back to 06
└── 13 Paper trade execution (MCP) - token verified    tool
```

How the pieces join one trace:

* inside the API process, OpenTelemetry context propagation nests everything under the
  active section;
* the **A2A** agents receive `trace_id` and `parent_span_id` in the A2A message metadata and
  open their span with `trace_context=...`, so remote work appears in the caller's trace
  even when the agent runs as a separate service (`docker compose`);
* the run pauses for approval; when it resumes (possibly after a server restart) the stored
  trace id is reused.

Only this project's spans are exported (`should_export_span=is_langfuse_span`): the MCP SDK
emits its own OpenTelemetry spans that would otherwise appear as loose top-level entries.

## 2. Scores

Every score is registered as a Langfuse **score config** on startup
(`app/observability/scores.py`), so the UI shows its description and range.

| Score | Source | Meaning |
|---|---|---|
| `rag_faithfulness` | RAGAS Faithfulness (LLM judge) | share of the report's claims supported by the retrieved passages |
| `rag_answer_relevancy` | RAGAS Answer Relevancy (judge + embeddings) | does the report address the question |
| `rag_context_precision` | RAGAS Context Precision without reference | are the useful chunks ranked first |
| `rag_context_relevance` | RAGAS Context Relevance | are the retrieved chunks relevant |
| `output_memo_quality` | RAGAS rubric score (1-5 -> 0-1) | accuracy, numbers, clarity, risk disclosure of the memo |
| `rag_citation_coverage` | deterministic | share of report sentences with a [n] citation |
| `rag_numeric_grounding` | deterministic | share of numbers in the report found in the sources |
| `rag_top_rerank_score` | deterministic | best cross-encoder score |
| `output_rule_extraction_accuracy` | deterministic vs truth file | mandate rules read correctly |
| `output_compliance_pass` | boolean | every mandate rule passes |
| `portfolio_oos_sharpe` | deterministic | out-of-sample Sharpe ratio |
| `portfolio_oos_excess_return_vs_benchmark` | deterministic | out-of-sample return minus S&P 500 / Nifty 50 |
| `portfolio_baseline_gap` | deterministic | how far the rule of thumb falls short of the best combination |
| `guardrail_input_blocked` | boolean | the input rail stopped the request |
| `guardrail_pii_redacted` | numeric | personal-data values removed from the request |
| `guardrail_quarantined_passages` | numeric | retrieved passages kept out of the prompt |
| `guardrail_output_violations` | numeric | memo checks the first draft failed |
| `self_corrections` | numeric | revisions after a failed check (research + memo) |
| `memory_items_recalled` | numeric | past reviews, preferences and notes recalled at intake |
| `research_cache_hit` | boolean | research answer reused from the semantic cache |
| `human_approved` | boolean | the advisor's decision |
| `human_revisions` | numeric | how many times the advisor pressed *Change* before deciding |
| `learned_preferences_applied` | numeric | remembered preferences applied to the first proposal |

RAGAS metrics need an LLM judge (Groq by default: `qwen/qwen3.8-27b`, each judge call
visible as a `judge.*` generation). Without a key they are skipped and the
run says so; they are never filled with made-up values.

## 3. Dataset and experiments

`uv run python scripts/eval_rag.py` creates (or updates) the dataset
**`quantfolio-rag-golden`** (78 items: facts, mandate and paraphrased US and India risk
questions, each with the chunk ids that answer it) and runs one experiment per retrieval mode
(`retrieval-bm25`, `retrieval-dense`, `retrieval-hybrid`, `retrieval-hybrid_rerank`) with
item scores `hit_rate@6`, `recall@6`, `mrr@6`, `ragas_id_context_precision`,
`ragas_id_context_recall` and a run-level `avg_hit_rate@6`.

In Langfuse: *Datasets → quantfolio-rag-golden → Experiments*, select the four runs and
compare.

`uv run python scripts/eval_guardrails.py` creates the dataset
**`quantfolio-guardrails-redteam`** (attacks and tricky benign requests with the expected
verdict) and an experiment run scored `guardrail_correct` per item.

## 4. Building the dashboard

In Langfuse open *Dashboards → New dashboard* ("QuantFolio quality") and add widgets:

| Widget | View | Metric | Breakdown / filter |
|---|---|---|---|
| RAG quality over time | Scores (numeric) | average `value` | filter name in `rag_faithfulness, rag_answer_relevancy, rag_context_precision`; line chart by day |
| Memo quality | Scores | average `output_memo_quality` | by tag (client) |
| Compliance pass rate | Scores (boolean) | average `output_compliance_pass` | total |
| Safety | Scores | sum of `guardrail_input_blocked`, `guardrail_quarantined_passages`, `guardrail_output_violations` | line chart by day |
| Self-correction | Scores | average `self_corrections` | by tag (client) |
| Approval rate | Scores | average `human_approved` | by tag |
| Learning loop | Scores | average `human_revisions` and `learned_preferences_applied` | line chart by week, per client tag: revisions should fall as learned preferences rise |
| Cost and latency per run | Traces | total cost, p95 latency | filter name = `portfolio-run` |
| LLM tokens by agent | Observations | total tokens | breakdown by observation name (`llm.*`) |

The score configs make these widgets self-describing. Tags (`C-101`, `ESG Growth`,
`llm:groq`) allow per-client and per-model breakdowns.
