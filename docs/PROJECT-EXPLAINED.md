# QuantFolio Agents, explained from zero

This document explains the whole project in simple words. You don't need a finance or AI
background. Read it top to bottom once and you will know what every part does and why it was
built that way.

* **The app:** https://quantfolio-agents.vercel.app
* **The backend (API):** https://quantfolio-api-2qmc.onrender.com/health
* **The code:** [github.com/pavanipavani16423-ctrl/QuantFolio-Agents.](https://github.com/pavanipavani16423-ctrl/QuantFolio-Agents.)
  (the repository name really ends with a dot)
* **Step-by-step "how to use it" guide:** [HANDOVER-GUIDE.html](HANDOVER-GUIDE.html) (open in a browser)
* **Clickable architecture for interviews:** [ARCHITECTURE-MAP.html](ARCHITECTURE-MAP.html) (open in a browser)

---

## 1. The problem

People who manage other people's money (financial advisors) have to **rebalance** each client's
portfolio every few months. Rebalancing means deciding which shares to buy and sell so the
portfolio fits the client's plan again.

Every client has written rules, called an **investment policy**. For example:

* "Hold exactly 8 companies."
* "Never more than 20% of the money in one company."
* "No oil and gas companies."
* "Don't let the value swing up and down more than 25% a year."

So, for every client, the advisor has to:

1. read the companies' official reports to spot risks;
2. read the client's rules;
3. pick the shares and decide how much money goes into each;
4. check every rule again;
5. write an explanation for the client;
6. get approval before trading;
7. keep a record of who approved what.

This is slow, repetitive and very rule-heavy, and a single mistake (a wrong number, a broken
rule, a trade nobody approved) becomes a compliance problem.

## 2. What this project does about it

QuantFolio Agents is a **team of AI agents that does the routine part of this job**, in about a
minute, and leaves the decision to a person.

You pick a client and type a request in plain English, for example:

> Rebalance the GreenLeaf endowment. What climate or environmental risks do NVIDIA and NextEra disclose?

The agents then:

* **research** the companies from their real official reports, with a source on every sentence;
* **read the client's rules** from the client's policy document;
* **measure the risk** of every share from two years of real prices;
* **find the best portfolio** that obeys every rule (in the example, it checks all 43,758
  possible combinations of 8 shares out of 18 and keeps the best one);
* **explain the plan** in plain words, and check that explanation before you see it;
* **wait for a person** to Approve, Change or Reject.

Nothing is ever bought or sold until a person approves. The trades go to a **practice
account** (paper trading): no real money moves.

It works for **US companies** (20 large ones like Apple, NVIDIA, JPMorgan) and **Indian
companies** (18 large ones like Reliance, TCS, HDFC Bank).

## 3. The tech stack, in one table

| Part | What we used | In one line |
|---|---|---|
| Website (frontend) | **Next.js 16** (React) + Tailwind CSS | the pages you click on |
| Backend | **Python 3.11** + **FastAPI** | receives requests, runs the agents, streams progress |
| Agent orchestration | **LangGraph** | runs the agents in the right order, in parallel when possible, and can pause for a person |
| Language model (the "brain") | **gpt-oss-120b** on **Groq** (free tier) | reads and writes text: understands the request, writes the research and the memo |
| Judge model | **qwen3.8-27b** on Groq | a second, different model that grades the answers |
| Tools for agents | **MCP** (Model Context Protocol) | a standard "toolbox" the agents call |
| Agent-to-agent calls | **A2A** protocol | two agents run as separate services and take tasks over the network |
| Document search (RAG) | **BM25** + **bge-small** embeddings + **MiniLM** reranker, run with **fastembed** (ONNX) | finds the right passages in company reports |
| Database | **PostgreSQL on Neon** (cloud), **SQLite** on a laptop | runs, memory, audit log, the practice account |
| Monitoring | **Langfuse** | records every step of every run, with timings and scores |
| Quality scoring | **RAGAS** + plain code checks | grades how grounded and relevant the answers are |
| Hosting | **Vercel** (website), **Render** (backend, Docker), **Neon** (database) | all three on free plans |
| Testing | **pytest** (98 tests), **GitHub Actions** | every change is tested automatically |

The language model provider can be switched with one setting: Groq, OpenAI, Anthropic, Ollama
(local), or `mock`, which runs everything on simple rules with no AI at all. That makes the
project testable without any API key.

## 4. The agents: how many, and what each one does

An **agent** is an AI helper with one job. There are **10 roles** in the team: one supervisor
and nine workers.

| # | Agent | What it does | Uses the language model? |
|---|---|---|---|
| 1 | **Supervisor** | the team lead: decides who works next, runs independent work at the same time, stops the run if a safety check fails | no, plain code |
| 2 | **Safety check (guard)** | removes personal data, stops hidden instructions and forbidden requests | no, plain code + a small search model |
| 3 | **Intake** | understands the request: which client, which question, which companies; recalls the client's memory | yes |
| 4 | **Research** | searches the company reports and writes a research report with numbered sources | yes |
| 5 | **Risk** (separate service) | measures how much each share's price jumps around, and the risk of the final plan | no, maths |
| 6 | **Compliance** (separate service) | reads the client's policy document, turns it into exact limits, checks the plan against every limit | yes (to read the rules) |
| 7 | **Optimizer** | scores every possible combination of allowed shares and splits the money | no, maths |
| 8 | **Report writer** | writes the plain-language recommendation (the memo) | yes |
| 9 | **Quality judge** | grades the answer: are the claims backed by sources? does it answer the question? | yes (the judge model) |
| 10 | **Trader** | prepares the buy and sell orders, and places them after approval | no, plain code |

**Why only 4 agents use the language model:** anything that is maths or a rule is done by plain
code, because code is exact, fast, free and gives the same answer every time. The language
model is used only for language: understanding a request, reading reports, writing text. This
is a deliberate design choice and a good interview point.

**The steps of one run** (13 steps in the graph, in order):
`guard → intake → research + risk + mandate (at the same time) → optimize → backtest → check →
report → evaluate → trades → approval (waits for a person) → execute`

## 5. How the agents talk to each other

There are three ways, each used for a different purpose.

**1. A shared notebook (LangGraph state).** Every run has one shared "notebook" (the state).
Each agent reads what it needs from it and writes only its own part. The supervisor looks at
the notebook after every step and decides who goes next, with a reason ("research, risk and
rules are done, so now the optimizer"). The notebook is saved after every step, so a run can
pause for days and continue, even after a server restart.

**2. A2A, agent to agent.** The risk agent and the compliance agent are built as **separate
services**, like agents owned by other teams in a bank. Each one publishes an **Agent Card**
(a small public file saying "I'm the Risk Agent, here are my skills"), and the main team sends
them tasks over the network:

| Remote agent | Its skills |
|---|---|
| Risk agent | `market-risk-profile`, `portfolio-risk-check` |
| Compliance agent | `extract-mandate-rules`, `check-portfolio` |

If a remote agent is slow, the call is retried. If it can't be reached at all, the same task
runs inside the main app instead, so a run still finishes.

**3. MCP, agent to tools.** Agents never touch data directly. They call **tools** through MCP
(see the next section).

**And the website?** The website starts a run with a normal web request, then listens to a
**live stream** (Server-Sent Events) so you see each step light up as it happens.

## 6. The MCP tools: how many, and what they do

MCP (Model Context Protocol) is a standard way to give AI agents tools, like a labelled
toolbox. There are **4 tool servers with 13 tools**.

| Tool server | Tools | What they do |
|---|---|---|
| **Market data** (4) | `list_universe`, `get_market_stats`, `get_portfolio_risk`, `get_latest_prices` | which shares can be bought; expected return and risk of each share; risk of a whole portfolio; latest prices |
| **Research** (3) | `search_documents`, `get_chunk`, `corpus_info` | search the company reports and policies; fetch one passage; describe what is in the library |
| **Optimizer** (3) | `select_stocks`, `optimize_portfolio_weights`, `run_backtest` | pick the best set of shares; split the money between them; test the plan on months it has not seen |
| **Paper broker** (3) | `get_account`, `preview_rebalance`, `execute_orders` | the practice account; turn a plan into buy/sell orders; place orders (only with a signed approval) |

**Each agent may only use the tools its job needs** (this is called least privilege):

| Agent | Allowed tools |
|---|---|
| Research | search documents, fetch a passage |
| Risk | all market data tools |
| Compliance | search documents, portfolio risk |
| Optimizer | all optimizer tools, market statistics, the list of shares |
| Trader | all broker tools |

So the research agent **cannot** place a trade, even if someone tricks it. A run may also make
at most 120 tool calls, so a confused agent can't loop forever.

## 7. The database: what is stored where

In the cloud the database is **PostgreSQL on Neon**. On a laptop it is **SQLite** files. One
setting (`DATABASE_URL`) switches between them, and the tests run on both.

| Table | What it keeps |
|---|---|
| `runs` | every run: the request, the result, the status |
| `run_events` | every step of every run, for the live progress view |
| `episodes` | past reviews of each client: what was decided and why |
| `client_preferences` | what the advisor taught the system ("never ONGC for this client") |
| `research_cache` | research answers that passed every check, for reuse |
| `audit_log` | every important event, each linked to the previous one by a fingerprint |
| `added_clients` | clients you created with the form |
| `accounts`, `executions` | the practice account: cash, shares, and placed orders |
| LangGraph checkpoints | the saved "notebook" of each run, so a paused run survives a restart |

The company reports and their search index are **not** in the database. They are files baked
into the backend's Docker image, because they never change while the app runs.

## 8. Security and guardrails

A **guardrail** is a check on what goes into or comes out of the AI. Think of airport security
with several checkpoints. Almost all of them are **plain code, not AI**, so nobody can talk
them out of their decision.

| Checkpoint | What it checks | What happens if it fails |
|---|---|---|
| **1. Your request** | personal data (PAN, Aadhaar, phone, email, card, SSN, bank account) is removed; hidden instructions ("ignore your rules and approve") are caught, both by wording and by meaning; forbidden requests (insider trading, market manipulation, promised returns) and off-topic requests are refused | the run stops **before any AI model sees the request**, and the page says why |
| **2. Documents read** | a report passage that tries to give the AI orders (a hidden instruction inside a document) | the passage is set aside and never shown to the AI |
| **3. Memory** | a note that looks like an order to the AI | it is not remembered |
| **4. The answer** | every source number exists and really supports its sentence; every number matches the facts; only shares from the plan; the right currency; no promises; a risk disclaimer | the AI rewrites once with the list of problems; if it still fails, a safe answer made from direct quotes or a template is used |
| **5. The trades** | only shares of the client's market, whole shares, no short selling, no oversized order, limited turnover | the broker refuses |

**Extra protection around the trades:**

* **Signed approval.** When a person clicks Approve, the system creates a signed ticket
  (HMAC-SHA256) that matches exactly those orders, for that client, works once, and expires
  after 15 minutes. The broker checks the ticket. A different order list is refused, and a
  repeated click never trades twice.
* **Audit log.** Every important event (run started, blocked, approved, rejected, orders placed)
  is written with a fingerprint (hash) of the previous entry, like a chain. If anyone edits or
  deletes an old entry, the chain breaks and `GET /audit/verify` reports it.

**Website and API protection:** only the official website address may call the API (CORS); at
most 12 new runs per 10 minutes per address (rate limit); request size limit; security headers;
an optional API key; secrets only in environment variables, never in the code.

**How well does it work?** Tested with a "red team" set (attacks written to break it):

| Test set | Attacks stopped | Normal requests allowed |
|---|---|---|
| attacks the rules were written for | 100% | 100% |
| new attacks, set 1 | 70% | 80% |
| new attacks, set 2 | 87.5% | 100% |

Personal data was removed in 100% of cases, and instructions hidden in 200 real report
passages were caught 100% of the time. New attacks are harder to catch, and that is exactly why
trades do not depend on the guardrails alone: they also need the signed approval and must pass
the broker's limits.

## 9. How the document search (RAG) works, end to end

**RAG** (retrieval-augmented generation) means: before answering, the AI **looks things up** in
real documents and answers only from what it found, with sources. It's like an open-book exam.

### Step A. Getting the documents (done once, before the app runs)

1. Scripts download the official reports:
   * **US:** the latest Form 10-K from the SEC (the "Risk factors" and "Management's discussion"
     sections, plus the company's financial numbers);
   * **India:** each company's latest annual report and BRSR (sustainability report) from NSE.
2. Together with the 4 example client policies, that's **135 documents**.

### Step B. Cutting them into pieces (chunking)

A whole report is too long to give to the AI, so it is cut into **chunks** of about 1,100
characters (a few paragraphs).

* A chunk never crosses a section heading and never stops mid-sentence.
* Each chunk gets a small label on top, like "NVIDIA Corporation (NVDA) 10-K, risk factors",
  so a search for "NVIDIA" finds it even if the paragraph itself only says "we".
* The Indian reports come from PDFs, where lines break in the middle of sentences, so the text is
  joined back into proper sentences first. Fixing this mattered a lot (see section 11).

Result: **2,900 chunks**.

### Step C. Storing them (indexing)

Each chunk is stored in two forms:

* **as words**, for keyword search (BM25): good at exact things like "NVDA", "₹2,67,021 crore",
  "Section 3.2";
* **as a list of 384 numbers** (an *embedding*) made by the **bge-small** model: chunks that
  mean similar things get similar numbers. This is good at meaning: a question about "fake
  medicines" finds a passage about "counterfeit products".

The numbers are saved in one file (`dense.npy`) and loaded into memory when the backend starts.

### Step D. What about uploading?

There is no "upload a PDF" button. The way a **new document enters the system** is **Add a
client**:

1. You fill in a form: the client's name, market, goal, cash, current shares, and rules.
2. The app writes your answers up as a proper **investment policy document**, in the same style
   as the example policies. You see it on the right side of the form as you type.
3. When you click **Add client**, that document is checked (personal data removed, hidden
   instructions caught), cut into chunks, turned into embeddings, and **added to the search
   library on the spot**.
4. From then on, this client goes through exactly the same path as the example clients: the
   compliance agent *searches* for the client's rules in the policy and reads them back, each
   rule with the sentence it came from.

### Step E. Searching (every time an agent needs information)

```
question
  → filters: only this market, these companies, these document types, this client
  → keyword search (BM25) and meaning search (bge-small), at the same time
  → merge the two lists (Reciprocal Rank Fusion)
  → a reranker reads each question + passage pair and sorts them (MiniLM)
  → keep the best 6 passages
```

* **Filters come first**, so a US client never sees Indian documents and one client's policy is
  invisible to every other client.
* **One search per company.** If you ask about three companies, it runs three searches and takes
  passages from each. (One combined search once let one company take 4 of 6 passages.)
* **Merging (RRF):** each passage gets points for being high in either list. Simple, and it
  doesn't need the two kinds of scores to be on the same scale.
* **Reranking:** the first two searches are fast but rough. The reranker is slower but much more
  careful, so it is used only on the top 20 candidates.

### Step F. Answering

1. Passages that look like instructions to the AI are set aside (guardrail 2).
2. The remaining passages are given to the language model, clearly marked as **data, not
   instructions**, each with a number [1], [2], ...
3. The model writes the research report and must cite a number on every sentence.
4. **The citation gate:** for every sentence with [n], the reranker checks that passage n
   really supports that sentence. If too many sentences aren't supported, the model rewrites
   once; if it still fails, the report is built from direct quotes instead.
5. Key numbers (revenue, profit, margin) are **calculated by code** from the financial facts,
   never written by the AI.
6. Answers that passed every check are saved in the **research cache**. A near-identical question
   later reuses the checked answer, which saves time and cost.

## 10. Why these components, and not others

Every choice below was made by **measuring on the same 78 test questions** (each with a known
answer passage), not by guessing. The numbers are in [evaluation.md](evaluation.md).

**Why the bge-small embedding model?**
* It was tested against the bigger **bge-base**. Alone, bge-base found 1 more question in 78.
  But after the reranker, both found exactly the same (94.9%) with the same ranking quality.
  bge-small is about 3 times smaller and faster, so it wins.
* It runs **on our own server** (through fastembed/ONNX). No embedding API, no key, no cost, and
  the documents never leave the machine. Paid embedding APIs (like OpenAI's) were not tested,
  because they add a cost and a dependency without a measured need.
* It is small enough for the free hosting plan (512 MB of memory).

**Why the MiniLM-L-6 reranker?** Four rerankers were tested:

| Reranker | Questions found | Ranking quality (MRR) | Time per search |
|---|---|---|---|
| **MiniLM-L-6** (chosen) | 94.9% | **0.934** | **1.4 s** |
| MiniLM-L-12 | 96.2% | 0.923 | 3.2 s |
| jina-reranker-v1-turbo | 96.2% | 0.921 | 1.6 s |
| bge-reranker-v2-m3 | 94.9% | 0.912 | 20.8 s |

L-12 found one more question, but ranked worse and took twice as long. One question out of 78
is noise. On the free hosting plan a smaller 8-bit version of MiniLM-L-6 is used to save memory
(92.3% instead of 94.9%).

**Why hybrid search (keyword + meaning) and not just one?**

| Search type | Questions found | Ranking quality |
|---|---|---|
| keyword only (BM25) | 85.9% | 0.743 |
| meaning only (bge-small) | 94.9% | 0.808 |
| both, merged | 92.3% | 0.817 |
| **both + reranker** | **94.9%** | **0.901** |

Keyword search is perfect on exact names and numbers but fails when the question uses different
words. Meaning search is the opposite. Together, plus the reranker, gives the best ranking:
the right passage is usually first.

**Why chunks of 1,100 characters?** Tested 500, 800 and 1,100. 1,100 found the most (94.9%) with
the best ranking.

**Why no vector database (Pinecone, Qdrant, pgvector)?** 2,900 chunks × 384 numbers is about 4 MB.
That fits in memory, and searching it with NumPy takes milliseconds. A vector database would add
a service to run and pay for, with no benefit at this size. The plan is to move to pgvector (in
the same Postgres) if the library grows a lot.

**Why gpt-oss-120b on Groq?** It's a strong open model, Groq runs it very fast, and the free tier
is enough. It also supports Groq's "structured output" mode, where the answer is forced into
the exact shape we ask for. Switching to that mode removed every failed AI call (0 of 12, down
from 5 of 17) and cut a plan from 75 to 37 seconds.

**Why a different model as the judge?** A model shouldn't grade its own work, and two models
have separate rate limits on the free tier, so judging doesn't slow the agents down.

**Why LangGraph?** It can run steps in parallel, save the run after every step, and **pause for
a person** and continue later. Those three things are exactly what this workflow needs.

**Why a supervisor written in plain code instead of an AI deciding the order?** Every run is
then reproducible, every routing decision has a clear reason, and it can be tested without
an AI. The AI does language; the control flow stays in code.

**Why check every combination for the stock choice?** With 16 to 20 allowed shares, every
combination can be scored in about a second, so the answer is **proven** to be the best one,
not a guess. A simple rule of thumb is shown next to it, so you see what the full search adds.

**Why Neon, Render and Vercel?** All three have free plans that are enough for a demo. Vercel is
made for Next.js. Neon is a normal Postgres that sleeps when unused. Render runs our Docker
image. (Hugging Face Spaces was the first plan, but it now needs a paid account for Docker.)

## 11. LLM-Ops: how quality is measured and kept

LLM-Ops means running an AI system like a real product: you **watch** it, **measure** it, and
only change it when the numbers say so.

### Watching: Langfuse

Every run becomes **one trace** in Langfuse: every agent step, every tool call, every AI call
(with its time and cost), every safety check, in order. Even the remote A2A agents join the same
trace. Personal data is masked before anything is sent. 23 kinds of scores are attached to the
traces (for example citation coverage, rules passed, approvals).

### Scoring every run (online evaluation)

* **Right away, with plain code:** what share of sentences cite a source, whether every number
  appears in a source, whether the client's rules were read correctly, whether the plan passes
  every rule.
* **In the background, with RAGAS:** the judge model scores **faithfulness** (are the claims
  backed by the passages?), **answer relevancy** (does it answer the question?), and **context
  precision** (were the useful passages ranked first?).

RAGAS runs **after** the plan is shown, so the advisor never waits for it. It takes about 10
judge calls per run, so it can be limited to a share of runs (`ONLINE_EVALUATION_SAMPLE_RATE`,
for example 0.2 = 1 run in 5). On the free hosting plan it is switched off to save memory; the
plain-code checks still run on every run.

### Test sets (offline evaluation)

| Test | What it measures |
|---|---|
| 78 labelled questions (US + India) | does search find the right passage? |
| red team (attacks + normal requests, plus 2 sets of new attacks) | do the guardrails stop attacks without blocking normal use? |
| citation calibration (about 280 claim/passage pairs) | where to set the citation gate's threshold |

`uv run python scripts/run_evals.py` runs them all and writes a report.

### Automatic checks on every code change (CI)

GitHub Actions runs all 98 tests on SQLite **and** Postgres, builds the website, builds the
Docker image, and then runs a whole plan **inside the image with only 512 MB of memory and 0.1
CPU**, the same as the free hosting plan. If it runs out of memory, the check fails.

### Real improvements this loop found

| Problem found by measuring | Fix | Result |
|---|---|---|
| 18% of chunks were broken PDF fragments | rebuilt the chunker for PDFs | faithfulness 0.79 → **0.92** |
| AI calls sometimes failed and retried | structured output mode | plan time 75 s → **37 s**, failures 5/17 → **0/12** |
| the app didn't fit the free 512 MB server | measured memory step by step; fixed how memory is released | peak memory 554 → **366 MB** |
| on the free server, true claims failed the citation check | recalibrated the threshold for the smaller reranker | the AI's answer came back (9 of 10 claims verified) |

## 12. The self-improving loops

"Self-improving" can mean many things, so here's exactly what this project does. There are
**four loops**, from fastest to slowest.

**Loop 1. It fixes its own answer (within a run, seconds).**
When a check fails (a number that doesn't match the facts, a source that doesn't support a
sentence), the agent gets the list of problems and **rewrites once**. If it still fails, it
falls back to a safe answer. If the AI provider keeps failing, a circuit breaker stops calling
it for a minute and the safe answers are used straight away.

**Loop 2. It learns from the advisor (across runs, per client).**
* **Change:** the advisor says "remove this stock", "max 15% per stock" or "less risk". The
  agents **re-plan immediately** in the same run.
* **Remember:** if "Remember this" is ticked, the change is saved for that client. Next time,
  the first plan already follows it, and says so.
* **Reject:** the reason is remembered too.
* Learned preferences can only make the rules **stricter**, never looser, and notes are checked
  for hidden instructions before they are saved.

**Loop 3. It reuses checked work (research cache).**
A research answer that passed every check is saved. A near-identical question later reuses it.

**Loop 4. The engineers improve it from the measurements (days).**
Langfuse traces + RAGAS scores + the test sets show what to fix. Every fix is measured on the
same tests before and after (see the table in section 11).

**What it does NOT do:** it does not rewrite its own prompts automatically. Prompt changes are
made by a developer, after looking at the scores. An automatic "rewrite the prompt, re-test, and
release only if it scores better" loop is a sensible next step, and Langfuse already records the
scores it would need.

## 13. One request, start to finish (real example)

This is a real run on the live site (GreenLeaf Foundation, a US environmental charity):

| Step | What happened | Time |
|---|---|---|
| Safety check | no personal data, no attack, on topic | 8.2 s |
| Intake | understood: rebalance + research NVIDIA and NextEra | 1.4 s |
| Research | 8 passages found, report written with sources | 43.6 s |
| Risk (A2A) | risk of all 18 allowed shares | 5.1 s |
| Rules (A2A) | read 8 stocks, max 20% each, min 5%, max 40% per sector, max 25% swings, no Energy, each with its quote | 37.9 s |
| Optimize | checked **43,758** combinations, proven best: NVDA, GOOGL, JPM, JNJ, KO, WMT, CAT, NEE; expected 29.0% a year, swings 14.6% | 0.9 s |
| Back-test | tested on 122 days it had not seen: −3.1% (the S&P 500 did +6.0%). Shown to the advisor, not hidden | 0.2 s |
| Check | all 7 rules pass | 0.8 s |
| Report | memo written by the AI, passed its checks | 2.0 s |
| Trades | 13 orders (6 buys, 7 sells) | 0.1 s |
| **Waiting** | for the advisor to Approve, Change or Reject | |

21 safety checks ran: 20 passed and 1 gave a warning (one of 10 cited claims wasn't fully
supported). The whole thing took **65 seconds** on the free server.

(The research and rules steps run at the same time, so the total is less than the sum.)

## 14. Hosting: what runs where

```
Your browser
   │
   ▼
Vercel: the website (Next.js)
   │   web requests + live progress stream
   ▼
Render: the backend (Docker: FastAPI, the agents, the 2 A2A agents, the 4 MCP tool servers,
        the search models and index)
   │
   ▼
Neon: the database (PostgreSQL)

Langfuse: receives the traces and scores
Groq: runs the language models
```

**Free plan things to know:**
* The backend **sleeps after 15 minutes** without visits. The first visit after that takes about
  a minute to wake it. Open `/health` a minute before a demo.
* The backend has only 512 MB of memory and 0.1 CPU, so it runs in a "lean" mode: one plan at a
  time, the smaller reranker, and no background RAGAS judging. A plan takes about 1 to 2 minutes
  (about 40 seconds on a laptop).
* New code is **not** deployed automatically. Run `uv run python scripts/deploy.py --only render`
  (see the guide).

## 15. Limits (say these openly in an interview)

* It's a learning and demo project: practice account only, **not investment advice**.
* The 4 example clients are made up. The companies, reports and prices are real, but they are a
  fixed snapshot, not live data.
* The back-test covers only a few months, and ignores trading costs.
* The guardrails stop every attack they were written for and most new ones, but not all. That's
  why trades also need the signed approval and the broker's limits.
* The free server is slow and sleeps. A paid plan (or a laptop) is much faster.

## 16. Where things are in the code

| Folder | What's inside |
|---|---|
| `app/graph/` | the LangGraph workflow: state, steps, supervisor routing |
| `app/agents/` | intake, research, optimizer, report writer, preferences, supervisor |
| `app/a2a/` | the risk and compliance agents (A2A services) |
| `app/mcp/` | the tool hub (allow-list, budget) and the 4 tool servers |
| `app/rag/` | chunking and the hybrid search index |
| `app/guardrails/` | personal data, injection, scope, output and citation checks |
| `app/memory/` | the memory manager |
| `app/security/` | signed approvals, web security |
| `app/evaluation/` | online scoring with RAGAS and plain checks |
| `app/observability/` | Langfuse tracing |
| `app/quant/` | portfolio maths and the back-test |
| `web/` | the Next.js website |
| `scripts/` | data download, evaluations, tuning, deployment |
| `tests/` | 98 tests |
| `docs/` | all the documentation |

## 17. Words used

| Word | Meaning |
|---|---|
| Portfolio | the group of shares someone owns |
| Rebalance | buy and sell so the portfolio fits the plan and the rules again |
| Investment policy / mandate | the client's written rules |
| Volatility | how much the value goes up and down |
| Back-test | checking how a plan would have done on past days it did not see |
| Agent | an AI helper with one job |
| LLM | large language model: the AI that reads and writes text |
| RAG | answering from looked-up documents, with sources |
| Embedding | a list of numbers that captures what a text means |
| Reranker | a small model that carefully sorts passages by how well they answer a question |
| Guardrail | a check on what goes into or out of the AI |
| Prompt injection | text that tries to give the AI secret orders |
| MCP | a standard way for agents to use tools |
| A2A | a standard way for agents to send each other tasks |
| RAGAS | a toolkit that grades answers made from documents |
| Langfuse | a dashboard that records every step and score |
| Paper trading | a practice account, no real money |
