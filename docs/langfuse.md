# Langfuse: tracing, scores and experiments

QuantFolio Agents sends three kinds of data to Langfuse (Python SDK v5, OpenTelemetry based):

1. **One trace per run**, with one clearly numbered section per agent step.
2. **Scores on every trace**: RAGAS quality metrics, deterministic checks, portfolio and
   quantum numbers, and the human approval decision.
3. **A dataset with experiment runs**: the labelled RAG test set, evaluated once per
   retrieval mode, so the modes can be compared side by side.

Tracing is off until `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set (`.env`); the
code path is the same either way.

## 1. The trace of a run

Open a run in the web UI and click **See every step in Langfuse**, or open *Tracing → Traces*
in Langfuse and filter by tag (client id, profile, `llm:groq`, `start`/`resume`).

```text
portfolio-run                                          chain    (user = client, session = client-<id>)
├── 01 Intake agent - understand the request           agent
│   └── llm.intake                                     generation  model, prompt, tokens, latency
├── 02 Research agent - hybrid RAG over SEC filings    agent
│   ├── rag.search: <question>                         retriever   BM25 / dense / fused / reranked ids
│   │   └── mcp.research.search_documents              tool
│   └── llm.research_answer                            generation
├── 03 Risk agent (A2A) - market risk profile          agent
│   └── A2A risk-agent: market-risk-profile            agent       <- span created by the remote service
│       └── mcp.market.get_market_stats                tool
├── 04 Compliance agent (A2A) - read the client mandate
│   └── A2A compliance-agent: extract-mandate-rules    agent
│       ├── mcp.research.search_documents  (x7)        tool
│       └── llm.compliance_extract_rules               generation
├── 05 Portfolio optimizer - classical vs quantum vs hybrid
│   ├── mcp.optimizer.select_classical                 tool
│   ├── mcp.optimizer.select_quantum                   tool        qubits, depth, QAOA metrics
│   ├── mcp.optimizer.refine_hybrid                    tool
│   └── mcp.optimizer.optimize_portfolio_weights (x4)  tool
├── 06 Backtest - out-of-sample performance            tool
├── 07 Compliance and risk check (A2A)                 guardrail   WARNING level if a rule fails
├── 08 Report writer - investment memo                 agent
├── 09 Quality evaluation - RAGAS and checks           evaluator
│   └── judge.<RAGAS prompt>  (several)                generation  the RAGAS judge's own calls
└── 10 Trade proposal - paper broker (MCP)             tool
portfolio-run  (resume, same trace id, after the human decision)
├── 11 Human approval                                  span
└── 12 Paper trade execution (MCP)                     tool
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
| `rag_faithfulness` | RAGAS Faithfulness (LLM judge) | share of the answer's claims supported by the retrieved filings |
| `rag_answer_relevancy` | RAGAS Answer Relevancy (judge + embeddings) | does the answer address the question |
| `rag_context_precision` | RAGAS Context Precision without reference | are the useful chunks ranked first |
| `rag_context_relevance` | RAGAS Context Relevance | are the retrieved chunks relevant |
| `output_memo_quality` | RAGAS rubric score (1-5 → 0-1) | accuracy, numbers, clarity, risk disclosure of the memo |
| `rag_citation_coverage` | deterministic | share of answer sentences with a [n] citation |
| `rag_numeric_grounding` | deterministic | share of numbers in the answer found in the sources |
| `rag_top_rerank_score` | deterministic | best cross-encoder score |
| `output_rule_extraction_accuracy` | deterministic vs truth file | mandate rules read correctly |
| `output_compliance_pass` | boolean | every mandate rule passes |
| `portfolio_oos_sharpe` | deterministic | out-of-sample Sharpe ratio |
| `portfolio_oos_excess_return_vs_spy` | deterministic | out-of-sample return minus SPY |
| `quantum_optimality_gap` | deterministic | QAOA vs exact optimum (0 = optimal) |
| `quantum_feasible_probability` | deterministic | probability mass on valid selections |
| `quantum_approximation_ratio` | deterministic | QAOA approximation ratio |
| `human_approved` | boolean | the advisor's decision |

RAGAS metrics need an LLM judge (Groq by default: a pool of `qwen/qwen3.8-27b` and
`openai/gpt-oss-120b`, used in turn, each judge call visible as a `judge.*` generation). Without a key they are skipped and the
run says so; they are never filled with made-up values.

## 3. Dataset and experiments

`uv run python scripts/eval_rag.py` creates (or updates) the dataset
**`quantfolio-rag-golden`** (47 items: facts, mandate and paraphrased risk questions, each
with the chunk ids that answer it) and runs one experiment per retrieval mode
(`retrieval-bm25`, `retrieval-dense`, `retrieval-hybrid`, `retrieval-hybrid_rerank`) with
item scores `hit_rate@6`, `recall@6`, `mrr@6`, `ragas_id_context_precision`,
`ragas_id_context_recall` and a run-level `avg_hit_rate@6`.

In Langfuse: *Datasets → quantfolio-rag-golden → Experiments*, select the four runs and
compare.

## 4. Building the dashboard

In Langfuse open *Dashboards → New dashboard* ("QuantFolio quality") and add widgets:

| Widget | View | Metric | Breakdown / filter |
|---|---|---|---|
| RAG quality over time | Scores (numeric) | average `value` | filter name in `rag_faithfulness, rag_answer_relevancy, rag_context_precision`; line chart by day |
| Memo quality | Scores | average `output_memo_quality` | by tag (client) |
| Compliance pass rate | Scores (boolean) | average `output_compliance_pass` | total |
| Quantum gap | Scores | average `quantum_optimality_gap` | line chart |
| Approval rate | Scores | average `human_approved` | by tag |
| Cost and latency per run | Traces | total cost, p95 latency | filter name = `portfolio-run` |
| LLM tokens by agent | Observations | total tokens | breakdown by observation name (`llm.*`) |

The score configs make these widgets self-describing. Tags (`C-101`, `ESG Growth`,
`llm:groq`) allow per-client and per-model breakdowns.
