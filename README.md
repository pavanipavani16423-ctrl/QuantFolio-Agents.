# QuantFolio Agents

**An AI investment team that rebalances client portfolios in the US and India: multi-agent
(LangGraph), agent-to-agent (A2A), MCP tools, hybrid RAG over each market's mandatory company
disclosures (SEC filings; SEBI annual reports and BRSR), a quantum optimizer (QAOA), Langfuse
tracing, RAGAS evaluation, and a human-in-the-loop that learns from the advisor's changes.**

New here? Read the plain-English guide: [docs/GUIDE.md](docs/GUIDE.md), or open the visual guide
[docs/quantfolio-guide.html](docs/quantfolio-guide.html) in a browser (one self-contained file you
can share).

![Home](docs/screenshots/guide-1-start.png)

---

## Contents

1. [What it does](#what-it-does)
2. [Who it is for](#who-it-is-for)
3. [Architecture](#architecture)
4. [The agents](#the-agents)
5. [Hybrid RAG](#hybrid-rag)
6. [Where quantum fits](#where-quantum-fits)
7. [Observability: Langfuse](#observability-langfuse)
8. [Evaluation: RAGAS and experiments](#evaluation-ragas-and-experiments)
9. [Results](#results)
10. [Quick start](#quick-start)
11. [Configuration](#configuration)
12. [API](#api)
13. [Tests](#tests)
14. [Project layout](#project-layout)
15. [Data](#data)
16. [Limitations](#limitations)

---

## What it does

Every quarter, wealth managers rebalance client portfolios. They read company annual reports,
apply each client's investment policy (how many stocks, how much in one stock or one industry,
what to exclude, how much risk), pick the stocks, check the result and write a memo. QuantFolio
Agents automates that routine end to end and shows its work:

1. You pick a client and write a request, e.g. *"Rebalance the GreenLeaf endowment. What
   climate or environmental risks do NVIDIA and NextEra disclose?"*
2. The **research agent** answers from the companies' 10-K filings, with clickable citations.
3. The **compliance agent** (a separate A2A service) reads the client's policy document and
   turns it into machine-checkable rules, each linked to the sentence it came from.
4. The **risk agent** (a separate A2A service) estimates returns, covariance, VaR and beta.
5. The **optimizer agent** chooses the stocks three ways on the same problem: exact search on
   a normal computer, **QAOA on a simulated quantum computer**, and a hybrid of the two. It then
   sets the weights under the mandate's limits.
6. The portfolio is **backtested on months the agents never saw**, checked rule by rule, and
   written up as a plain-language memo.
7. Every answer is **scored** (RAGAS and deterministic checks) and sent to **Langfuse**.
8. The run **pauses for a human**: **Approve**, **Change** or **Reject**. *Change* (remove a
   stock, a smaller maximum per stock, less risk) makes the agents re-plan at once; with
   "remember" ticked the preference is stored for that client and applied to every later plan
   (a learning loop measured in Langfuse by approvals and revisions). Only after approval does
   the trader agent place the orders, in a paper (practice) account.

![Run page](docs/screenshots/guide-4-plan.png)

### Two markets, two sets of research criteria

| | United States (20 stocks) | India (18 NSE stocks) |
|---|---|---|
| Regulator | SEC | SEBI |
| Research documents | Form 10-K Item 1A (risk factors), Item 7 (MD&A), XBRL facts | Annual report: Management Discussion and Analysis (SEBI LODR Reg. 34) and its risk paragraphs; Business Responsibility and Sustainability Report (BRSR); reported financials in ₹ crore |
| Prices, currency, benchmark | Yahoo Finance, USD, S&P 500 (SPY) | Yahoo Finance (NSE), INR, Nifty 50 |
| Risk-free rate (Sharpe) | 4.0% | 6.5% |
| Example client | 3 mandates (C-101..C-103) | Sharma Family Trust (C-201): 8 stocks, no tobacco |

The research agent picks the document types from the client's market, the compliance agent
reads that client's mandate, and the backtest compares against the market's own index.

## Who it is for

* **Advisors and portfolio managers** who rebalance many accounts and must explain each
  change in plain language.
* **Compliance teams**, who need proof that every client rule was read correctly and checked,
  with citations.
* **Researchers and students** who want to test quantum optimization on a real business
  problem, against an exact classical answer, inside a production-style agent system.

## Architecture

```mermaid
flowchart LR
    UI["Next.js UI<br/>live progress (SSE)<br/>approve / reject"] -->|REST + SSE| API["FastAPI<br/>run service"]
    API --> G["LangGraph<br/>supervisor + agents<br/>SQLite checkpoints"]
    G -->|A2A JSON-RPC| RISK["Risk agent<br/>A2A service"]
    G -->|A2A JSON-RPC| COMP["Compliance agent<br/>A2A service"]
    G -->|MCP| MCP1["research server<br/>hybrid RAG"]
    G -->|MCP| MCP2["optimizer server<br/>exact / QAOA / hybrid / backtest"]
    G -->|MCP| MCP4["paper broker server"]
    RISK -->|MCP| MCP3["market-data server"]
    COMP -->|MCP| MCP1
    MCP2 --> Q["Qiskit + Aer<br/>QAOA (XY mixer)"]
    MCP1 --> IDX["BM25 + bge-small<br/>RRF + cross-encoder"]
    G -->|LLM calls| LLM["Groq / OpenAI / Anthropic"]
    G -. traces + scores .-> LF[("Langfuse")]
    RISK -. same trace .-> LF
    COMP -. same trace .-> LF
    API --> DB[("SQLAlchemy<br/>SQLite / Postgres")]
```

* **LangGraph** runs the agents as a graph around a supervisor. Independent work (research,
  risk, mandate) runs in parallel in one superstep. The approval step uses `interrupt()`, and
  the SQLite checkpointer makes the pause durable: a run that is waiting for approval survives
  a server restart.
* **A2A (agent-to-agent protocol 1.0, `a2a-sdk`)**: the risk and compliance agents publish
  Agent Cards (`/a2a/risk/.well-known/agent-card.json`) and accept tasks over JSON-RPC. By
  default the API server hosts them, so `localhost` calls go over real HTTP. With
  `docker compose` they run as separate containers. The caller passes its Langfuse trace id
  in the A2A message metadata, so remote work appears in the same trace.
* **MCP (Model Context Protocol)**: four servers (market data, research, optimizer, paper
  broker) expose 15 tools. Each agent gets a toolbox limited by an allow-list
  (least privilege). The servers cap qubits, shots and iterations whatever the caller asks.
  Transport: in-process (default) or stdio subprocesses.

### One run, step by step

```mermaid
sequenceDiagram
    participant U as Advisor (UI)
    participant S as Supervisor
    participant R as Research agent
    participant K as Risk agent (A2A)
    participant C as Compliance agent (A2A)
    participant O as Optimizer agent
    participant W as Report + judge
    participant T as Trader agent
    U->>S: request + client
    S->>S: intake
    par in parallel
        S->>R: research question
        R->>R: hybrid RAG (MCP) + LLM answer with [n] citations
    and
        S->>K: market-risk-profile
    and
        S->>C: extract-mandate-rules
        C->>C: RAG over the policy + LLM, sanity-checked
    end
    S->>O: optimize (exact | QAOA | hybrid, same QUBO)
    O->>O: weights, backtest on unseen months
    S->>C: check-portfolio
    S->>K: portfolio-risk-check
    alt volatility limit fails
        S->>O: re-optimize with doubled risk aversion (once)
    end
    S->>W: memo, then RAGAS + checks -> Langfuse scores
    S->>T: preview trades (paper broker)
    T-->>U: interrupt(): approve?
    U->>T: approve / reject
    T->>T: execute (idempotent, needs approval id)
```

## The agents

| Agent | Job | Tools |
|---|---|---|
| Supervisor | deterministic routing, parallel fan-out, one re-optimization loop, stop on a broken rule | none |
| Intake agent | extract client, research question, tickers mentioned (LLM, with rules as fallback) | none |
| Research agent | hybrid RAG over 10-K risk factors, MD&A and XBRL facts; cited answer | `research.*` |
| Risk agent (A2A) | expected returns, Ledoit-Wolf covariance, VaR, CVaR, beta, drawdown | `market.*` |
| Compliance agent (A2A) | read the client's policy statement into rules (LLM + pattern cross-check, stricter value wins), check the portfolio | `research.search_documents` |
| Optimizer agent | exact, QAOA and hybrid stock selection, then mean-variance weights, then backtest | `optimizer.*` |
| Report writer | plain-language memo from the computed facts only | none |
| Quality judge | RAGAS metrics + deterministic checks, written to Langfuse | none |
| Trader agent | preview and (after approval) execute paper trades | `broker.*` |

Every LLM call has a deterministic fallback, so the system also runs fully offline (no API
key), and the UI and the trace say which mode produced each answer.

## Hybrid RAG

```mermaid
flowchart LR
    Q[question + filters] --> B[BM25<br/>keyword]
    Q --> D[bge-small embeddings<br/>meaning]
    B --> F[Reciprocal Rank Fusion]
    D --> F
    F --> X[cross-encoder rerank<br/>ms-marco MiniLM]
    X --> A[top-k chunks with ids]
```

* **Corpus**: 135 documents, 4,585 chunks.
  * US: Item 1A (risk factors) and Item 7 (MD&A) of the latest 10-K for 20 companies, and SEC
    XBRL financial facts.
  * India: from each of 18 companies' latest annual report on NSE, the Management Discussion
    and Analysis (SEBI LODR Reg. 34), its risk paragraphs and the BRSR sustainability report
    (Titan publishes its BRSR separately, so it is skipped; NTPC uses FY2024-25 because the
    newest PDF is damaged), plus reported financials in ₹ crore (`scripts/fetch_india.py`).
  * 4 client policy statements (3 US, 1 India).
* **Contextual chunk headers** ("NVIDIA Corporation (NVDA) 10-K Item 1A risk factors -
  Risks Related to Demand, Supply, and Manufacturing") are indexed with each chunk.
* **Metadata filters** (ticker, document type, client, market) are applied before scoring.
* **Diversification**: the research agent spreads the top slots across the companies asked
  about.
* Models run locally on CPU via `fastembed` (ONNX). No embedding API is needed.

## Where quantum fits

Choosing *k* stocks out of *n* is a yes/no decision per stock: **one qubit per stock**. The
optimizer turns the mean-variance objective into a QUBO and runs QAOA on Qiskit Aer:

* **XY-mixer QAOA** (default) starts in a Dicke state and uses a ring XY mixer, so every
  measured portfolio has exactly *k* stocks. The standard X-mixer QAOA is kept for
  comparison.
* 18-20 qubits, depth p = 2, COBYLA, 2,048 shots. An exact NumPy simulation of the same
  unitaries (tested against Aer to 1e-9) speeds up the angle optimization; the final shots
  come from the real circuit on Aer.
* The exhaustive classical search gives the **proven optimum** of the same problem, so the
  quantum result is measured, not assumed. Details: [docs/quantum.md](docs/quantum.md).

![Normal vs quantum](docs/screenshots/guide-7-details.png)

## Observability: Langfuse

One trace per run, with a numbered section per agent (agent, retriever, tool, guardrail,
evaluator and generation observation types). Each LLM call is a generation with tokens and
latency, and each MCP call is a tool span. Remote A2A work is nested in the same trace.

```text
portfolio-run
├── 01 Intake agent - understand the request
├── 02 Research agent - hybrid RAG over SEC filings
│   ├── rag.search: <question>          (retriever: BM25 / dense / fused / reranked ids)
│   └── llm.research_answer             (generation)
├── 03 Risk agent (A2A)  └── A2A risk-agent: market-risk-profile   <- from the remote service
├── 04 Compliance agent (A2A) └── A2A compliance-agent: extract-mandate-rules
├── 05 Portfolio optimizer  ├── mcp.optimizer.select_classical / select_quantum / refine_hybrid
├── 06 Backtest - out-of-sample performance
├── 07 Compliance and risk check (A2A)   (guardrail)
├── 08 Report writer - investment memo
├── 09 Quality evaluation - RAGAS and checks   (+ the judge's own generations)
├── 10 Trade proposal - paper broker (MCP)
├── 11 Human approval            (after resume, same trace)
└── 12 Paper trade execution (MCP)
```

16 score configs are registered at startup and attached to every trace: RAG quality,
output quality, compliance, portfolio, quantum and the human decision. See
[docs/langfuse.md](docs/langfuse.md) for the full list and a dashboard recipe.

## Evaluation: RAGAS and experiments

**Online (every run)**, written to the run's Langfuse trace:

* RAGAS 0.4 with an LLM judge (Groq by default): `rag_faithfulness`,
  `rag_answer_relevancy`, `rag_context_precision`, `rag_context_relevance`, and
  `output_memo_quality` (a RAGAS rubric score of the final memo).
* Deterministic checks: citation coverage, numeric grounding (every number in the answer
  must appear in a source), rule-extraction accuracy against a hand-written truth file,
  compliance pass, out-of-sample Sharpe and excess return, quantum gap / feasibility /
  approximation ratio, and the human decision.
* The judge's prompts are traced too. Without a judge key the LLM metrics are reported as
  skipped, never invented.
* **Models (Groq free tier)**: the agents use `openai/gpt-oss-120b` (low reasoning effort). The
  RAGAS judge is `qwen/qwen3.8-27b` (thinking off), a different model on purpose: Groq's rate
  limits are per model (8,000 tokens/min), so the judge never slows the agents down. A failed
  tool call is retried in plain-JSON mode; `JUDGE_MODEL` also accepts a comma-separated pool
  that is used in turn. The plan is ready for a decision in about 20 seconds; RAGAS scoring then
  finishes in the background (about 2-3 minutes on the free tier) and appears on the run page
  and in Langfuse. A change request cancels stale scoring and re-scores the new plan.

  Example scores from a live run (GreenLeaf, "climate risks of NVIDIA and NextEra"):
  faithfulness 0.75, answer relevancy 0.90, context precision 0.92, context relevance 1.00,
  memo quality 0.75, citation coverage 1.00, rule extraction 1.00, compliance pass 1.
  India (Sharma Family Trust, "risks Reliance and TCS report"): faithfulness 1.00, answer
  relevancy 0.80, context precision 0.70, context relevance 1.00, memo quality 0.75, rule
  extraction 1.00, compliance pass 1.

**Offline (`scripts/eval_rag.py`)**: a 78-question test set with known answer chunks
(38 facts questions generated from US and Indian financials, 12 policy questions, and 28
hand-written risk questions, 18 US and 10 India, worded differently from the reports). It is uploaded as the Langfuse dataset
`quantfolio-rag-golden`, with one experiment per retrieval mode.

**Quantum (`scripts/quantum_experiment.py`)**: QAOA vs exhaustive search for every client,
mixer and depth.

## Results

Full write-up: [docs/evaluation.md](docs/evaluation.md). Raw data: `experiments/results/`.

**Retrieval** (78 labelled questions, US and India, top 6 over all 4,585 chunks, no filters):

| Mode | hit rate@6 | MRR@6 | RAGAS ID context recall | US risk questions | India risk questions |
|---|---|---|---|---|---|
| BM25 keyword | 84.6% | 0.759 | 0.827 | 56% | 60% |
| Dense embeddings | **96.2%** | 0.822 | **0.955** | **89%** | **100%** |
| Hybrid (RRF) | 94.9% | 0.836 | 0.930 | 78% | **100%** |
| Hybrid + reranker (default) | 94.9% | **0.924** | 0.942 | 78% | **100%** |

Keyword search fails on reworded questions, embeddings handle them best, and the reranker
puts the right passage first most often (best MRR). Exact facts and policy questions are
found by every mode. These are measured on a test set that was not used for tuning. On 8
generated answers (4 US, 4 India) the RAGAS judge scores faithfulness at 0.79.

**Quantum vs exact** (each client's real problem, 17-20 qubits, US and India):

| Design | optimum found | mean gap | valid answers | mean time (simulated) | exact search |
|---|---|---|---|---|---|
| XY mixer + Dicke start (default) | **6/12**, 3/4 at p = 2 | 2.8% | **100%** | 6 s | 0.03-0.4 s |
| Standard X mixer + penalty | 1/12 | 14.8% | 22% | 41 s | 0.03-0.4 s |

The constraint-preserving circuit is what makes QAOA useful here. The Indian mandate is the
hardest case (best QAOA gap 9.9%); the hybrid swap step closes
every remaining gap. No quantum advantage is claimed: the classical search is exact and faster
at this size.

**Agents** (rule-based mode, no LLM key): the compliance agent extracts all 9 rules of all 3
mandates correctly (`output_rule_extraction_accuracy` = 1.0), every recommended portfolio
passes every rule, and the excluded sectors and companies never appear.

![Quality scores on a run](docs/screenshots/guide-6-checks.png)

## Quick start

Requirements: Python 3.11 with [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
git clone https://github.com/pavanipavani16423-ctrl/Quantum-Enhanced-Autonomous-Multi-Agent-System.git
cd Quantum-Enhanced-Autonomous-Multi-Agent-System
uv sync
cp .env.example .env          # optional: add GROQ_API_KEY and Langfuse keys

uv run uvicorn app.main:app --port 8000          # API + hosted A2A agents

cd web && npm install && npm run dev            # UI on http://localhost:3000
```

Open http://localhost:3000, pick a client and press **Start the agents**. A run takes about
20 seconds on a laptop (the quantum step is the slowest), then waits for your approval.

Docker (API, two A2A agent services, UI):

```bash
cp .env.example .env
docker compose up --build
```

Evaluations:

```bash
uv run python scripts/eval_rag.py              # RAG test set -> Langfuse dataset + experiments
uv run python scripts/quantum_experiment.py    # QAOA vs exact for every client
uv run python scripts/fetch_data.py            # refresh prices and filings (set SEC_USER_AGENT)
```

## Configuration

All settings are environment variables (or `.env`); see [.env.example](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `groq`, `openai`, `anthropic`, `ollama`, or `mock` (offline rules) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | - | provider keys |
| `LLM_MODEL` | provider default | Groq default: `openai/gpt-oss-120b` |
| `JUDGE_PROVIDER`, `JUDGE_MODEL` | Groq: `qwen/qwen3.8-27b` | RAGAS judge; a comma-separated list is used in turn |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | - | tracing and scores |
| `RAG_MODE` | `hybrid_rerank` | `bm25`, `dense`, `hybrid`, `hybrid_rerank` |
| `QAOA_MIXER` / `QAOA_REPS` / `QAOA_MAXITER` / `QAOA_SHOTS` | `xy` / 2 / 60 / 2048 | quantum settings |
| `TRAIN_END` | `2026-04-30` | end of the estimation window; later days are out of sample |
| `A2A_RISK_URL`, `A2A_COMPLIANCE_URL` | hosted by the API | run the agents elsewhere |
| `MCP_TRANSPORT` | `inprocess` | or `stdio` |
| `DATABASE_URL` | SQLite file | `postgresql+asyncpg://...` |
| `API_KEY` | - | require `X-API-Key` on `/api/v1` |

## API

| Method | Path | |
|---|---|---|
| GET | `/health` | LLM, judge, Langfuse, index status |
| GET | `/api/v1/clients` · `/clients/{id}/account` · POST `/clients/{id}/reset` | clients and paper accounts |
| POST | `/api/v1/runs` | start a run `{client_id, request, methods}` |
| GET | `/api/v1/runs` · `/runs/{id}` | run list / full run document |
| GET | `/api/v1/runs/{id}/events` | Server-Sent Events: steps, decisions, tool calls |
| POST | `/api/v1/runs/{id}/approval` | `{approved, reviewer, note}`; 409 if not waiting |
| GET | `/api/v1/chunks/{chunk_id}` · `/mandates/{client_id}` | citation viewer |
| GET | `/api/v1/system` · `/evaluations` | architecture (live) and experiment results |
| GET/POST | `/a2a/{risk,compliance}/.well-known/agent-card.json` · `/a2a/*/rpc` | A2A agents |

Interactive docs: http://localhost:8000/docs

## Tests

```bash
uv run pytest            # 49 tests: unit + end-to-end through the HTTP API
```

They cover the Dicke state and the fast simulator against Qiskit Aer, the QUBO against the
utility, exact search against brute force, the weight optimizer's limits, Ledoit-Wolf, the
backtest, rule extraction for every mandate, the LLM sanity check (stricter value wins), the
supervisor's routing including the retry loop, every retrieval mode, MCP permission denial,
broker idempotency, the RAGAS adapter, and a full run through the API with approval
(A2A over the in-process fallback). Tests never call an LLM or Langfuse.

## Project layout

```text
app/
  agents/        intake, research, optimizer, report, supervisor (routing rules)
  a2a/           risk + compliance agents (A2A servers), client with in-process fallback
  mcp/           hub (ACL, tracing, retries) + servers: market_data, research, optimizer, broker
  graph/         LangGraph state, nodes, workflow, per-step tracing context
  rag/           chunking, hybrid index (BM25, dense, RRF, rerank)
  quant/         return/risk statistics, selection + weights, backtest
  quantum/       QUBO, circuits (Dicke, XY mixer), fast simulator, QAOA solver
  evaluation/    online RAGAS + checks, RAGAS adapters (traced judge, local embeddings)
  observability/ Langfuse tracer, score configs
  services/      run service (background runs, SSE, approval resume)
  api/ db/       FastAPI routes, SQLAlchemy storage
web/             Next.js 16 UI (start, live run, history, quality, how it works)
scripts/         fetch_data, eval_rag, quantum_experiment, serve_agent
data/            prices, SEC filings and facts, client mandates, accounts, eval sets, index
experiments/     result JSON files
docs/            quantum.md, langfuse.md, evaluation.md, screenshots
tests/           unit + integration
```

## Data

* **Prices**: daily adjusted closes for 20 US large caps and SPY, 2024-01-02 to 2026-10-23,
  from Yahoo Finance (`yfinance`).
* **Filings**: Item 1A and Item 7 of each company's latest 10-K, and XBRL company facts, from
  SEC EDGAR (public). Long sections are trimmed to their first 40,000 characters.
* **Clients**: three synthetic investment policy statements and starting accounts, clearly
  marked as examples. No real person or client data.

## Limitations

* **Not investment advice**: paper trading only, a small fixed universe, buy-and-hold
  backtests without costs, and a short out-of-sample window (122 trading days).
* **No quantum advantage is claimed.** The quantum computer is simulated on a laptop; at
  18-20 assets the exhaustive classical search is exact and much faster. The point is the
  integration and an honest measurement.
* Expected returns come from 2.3 years of history (shrunk 50% toward the average). That is
  standard but noisy.
* In offline mode (no LLM key) answers are rule-based (extractive research answer, template
  memo) and the RAGAS LLM metrics are skipped.
