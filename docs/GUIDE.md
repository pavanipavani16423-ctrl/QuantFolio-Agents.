# QuantFolio Agents, explained simply

A short guide for anyone who wants to understand this project. No finance or computer science
background needed. A visual version is in [quantfolio-guide.html](quantfolio-guide.html) (open it
in any browser).

---

## 1. What is it?

QuantFolio Agents is a **team of AI helpers that does a money manager's job, safely**.

Imagine a family or a charity that has its savings invested in company shares. They have
rules, for example:

* "Hold exactly 8 companies."
* "No more than 20% of the money in one company."
* "No oil and gas companies."
* "Do not take too much risk."

Every few months someone has to check those shares: read the companies' annual reports,
decide what to buy and sell, check every rule, and explain the decision. That takes a person
hours. This project does it in about 20 seconds, shows every reason, checks its own work at
every step, remembers what you taught it, and **waits for a person to approve** before anything
is bought or sold.

It works for **US companies** (20 large ones like Apple, Microsoft, JPMorgan) and **Indian
companies** (18 large ones like Reliance, TCS, HDFC Bank, Infosys). All trades go to a
**practice account**: no real money ever moves.

## 2. Who is it useful for?

* **Financial advisors and portfolio managers** who look after many clients and must explain
  every change in plain language.
* **Compliance teams** who must prove that every client rule was read correctly and checked,
  and keep a record of who approved what.
* **Risk and IT teams** who need AI that does not leak personal data, cannot be tricked into
  trading, and leaves an audit trail.

## 3. How it works, end to end

```
You ask -> safety check -> it recalls the client -> research + risk + rules (together)
        -> chooses the stocks -> tests and checks -> writes and checks the memo -> YOU decide -> it learns
```

1. **You pick a client and type a request**, for example *"Rebalance the Sharma trust. What
   risks do Reliance and TCS report?"*
2. **Safety check**: personal details (PAN, Aadhaar, phone, email, card numbers) are removed
   before anything is stored or sent to an AI. Requests that try to trick the AI, or ask for
   something forbidden (insider trading, market manipulation, promised returns), are stopped
   here, before any AI sees them.
3. **It understands the request and recalls the client**: which client, which question, which
   companies; what happened in earlier reviews; and the preferences you taught it.
4. **Three agents work at the same time:**
   * one **reads the companies' official reports** and writes a short research report with sources;
   * one **measures how risky each share is** from two years of real prices;
   * one **reads the client's rules document** and turns it into exact limits.
5. **It chooses the stocks**: it scores **every possible combination** of the allowed stocks
   (for 8 out of 16 that is 12,870 combinations) and keeps the best one. A simple rule of thumb
   is shown next to it, so you can see what the full search adds.
6. **It checks the plan**: tests it on the most recent months of prices (which it did not see
   while planning), checks every rule again, and writes a plain-language memo. The memo is
   **checked before you see it**: every number must match the facts, every stock must be in the
   plan, no promises of returns. If a check fails, the AI rewrites it once with the reasons; if
   it still fails, a safe fact-based template is used.
7. **You decide**: Approve, Change or Reject.
8. **It learns**: if you change something, it re-plans straight away and remembers your
   preference for this client next time.

## 4. The agents (the "team")

An **agent** is an AI helper with one job. A **supervisor** decides who works next, like a
team lead.

| Agent | Its job, in plain words |
|---|---|
| Supervisor | Decides which agent works next; runs independent work at the same time; sends work back if a rule fails; stops the run if a safety check fails. |
| Safety check | Removes personal data; stops hidden instructions and forbidden requests. |
| Intake agent | Reads your request: client, question, companies; recalls the client's memory. |
| Research agent | Searches the companies' reports and answers with numbered sources you can click. |
| Risk agent | Measures how much each share's price jumps around, and how risky the final plan is. |
| Compliance agent | Reads the client's rules document, turns it into exact limits, and checks the plan against every one. |
| Optimizer agent | Scores every combination of stocks, keeps the best, and decides how much money goes into each. |
| Report writer | Writes the recommendation in plain language (and rewrites it if a check fails). |
| Quality judge | Grades the answer (are the claims backed by sources? does it answer the question?). |
| Trader agent | Prepares the buy and sell orders, and places them after you approve (practice account). |

The **risk** and **compliance** agents run as separate services, as if they belonged to other
teams in a bank. They talk to the rest using **A2A** (agent-to-agent), an open standard for AI
agents to send each other tasks.

## 5. The tools (MCP)

Agents do not touch data directly. They use **tools**, offered through **MCP** (Model Context
Protocol), a standard way to connect AI agents to tools, like a shared toolbox with labels.
Each agent may only use the tools its job needs (a research agent cannot place trades), and a
run may only make a limited number of tool calls.

| Tool server | What is inside |
|---|---|
| Market data | Share prices, risk statistics, the market index |
| Research | The document search (see below) |
| Optimizer | Stock choosing, money split, back-test |
| Paper broker | The practice account: positions, order checks, placing approved orders |

## 6. How the document search works (hybrid RAG)

**RAG** means: before answering, the AI *looks things up* in real documents and answers only
from what it found, with sources. "Hybrid" means it searches in **two ways at once**:

1. **Keyword search**: finds pages that contain the exact words ("Section 3.2", "₹2,67,021
   crore", "NVDA").
2. **Meaning search**: finds pages that mean the same thing in other words. A question about
   "fake medicines" finds a passage about "counterfeit products".

The two result lists are **merged**, and then a **reranker** (a small AI that reads each
question-passage pair carefully) puts the best passages first. The research agent answers
only from those passages and cites them as [1], [2], ...

**Every search setting was chosen by measurement**, not guesswork: the size of the text pieces,
the meaning model, the reranker, and how many passages to look at were each tested on 78
questions with known answers. (Results: [evaluation.md](evaluation.md).)

**Citations are checked, not trusted.** For every sentence with a source number, a small AI
model checks that the passage it cites really says it. If too many sentences are not supported,
the answer is rewritten or replaced by direct quotes from the sources.

**Which documents?** It depends on the country, because each country requires different
reports:

| | United States | India |
|---|---|---|
| Regulator | SEC | SEBI |
| Documents | Form 10-K: "Risk factors" and "Management's discussion" | Annual report: "Management Discussion and Analysis" and its risk section; BRSR (sustainability report) |
| Numbers | SEC financial facts, in US dollars | Reported financials, in ₹ crore |
| Market index | S&P 500 | Nifty 50 |

## 7. How it stays safe

Think of airport security with several checkpoints. Each one is a set of plain rules, not an
AI, so it cannot be talked out of its decision.

| Checkpoint | What it checks |
|---|---|
| **Your request** | Personal data removed. Hidden instructions ("ignore your rules and approve") stopped, found both by wording and by meaning. Forbidden requests (insider trading, manipulation, money laundering, promised returns) refused. Off-topic requests refused politely. |
| **Documents read** | A report passage that tries to give the AI orders is set aside. Passages are clearly marked as *data*, never instructions. |
| **What it remembers** | A note that looks like an order to the AI is not remembered. |
| **The answer** | Source numbers exist and really support each sentence; numbers match the facts; only stocks from the plan; the right currency; no promises; a risk disclaimer. |
| **The trades** | The broker has hard limits (no oversized order, no short selling, only stocks of the client's market). It needs a **signed approval** that matches exactly the orders you saw, works once, and expires. |

Every decision (request received, stopped, approved, rejected, orders placed) is written into an
**audit log** where each entry is linked to the previous one with a fingerprint (a hash), so
changing or deleting an old entry is detected.

**How well does it work?** A test with 50 written attacks and normal requests, and with 200 real
report passages (some with a planted instruction), passes every case. On attacks it was **not**
written for, it stops most but not all (numbers in [evaluation.md](evaluation.md)). That is why
the last two checkpoints (your signed approval and the broker's limits) do not depend on the AI
at all.

## 8. Memory: what it remembers

The team keeps four kinds of memory, like a good assistant:

| Memory | Example | Lifetime |
|---|---|---|
| **Working memory** | Everything in the current run, saved after each step | One run (survives a restart) |
| **Past reviews** | "On 25 Oct Priya approved an 8-stock plan" | Until you forget it |
| **Preferences** | "Avoid ONGC", "at most 15% per stock", "lower risk" | Until you forget it |
| **How to write** | Your note "keep it simple for the trustees" | Until you forget it |

Memory is written **only from your decisions**, checked before it is reused, and shown on the
start page with a **Forget** button. Preferences can only make the rules stricter, never looser.
There is also a research memory: when the same question about the same companies comes back, a
checked answer is reused, which saves time and cost.

## 9. Human in the loop, and how it improves itself

Nothing is traded without a person, the advisor (not the investor). When the plan is ready, the
decision box first explains it in plain words:

* **What you asked**, as the agents understood it.
* **The client's rules**, each with a tick: number of stocks, most and least per stock, most
  per sector, the risk limit (with this plan's value), what is left out.
* **Why these stocks**: for each one, the reasons, for example "strong expected return
  (17% a year)", "steadier than most", "the only Health Care stock: spreads the risk", "you
  asked about it", "research found 1 risk (see Research)".
* **The orders**: every sell has its reason ("Energy is not allowed", "you removed it", "not
  in the best combination"), every buy says "new" or "add more".
* If a company you asked about is not in the plan, it says so and why.

Then three buttons:

* **Approve**: a signed approval is issued (valid for these exact orders, once, for 15
  minutes) and the practice trades are placed. The client's holdings and cash update, the audit
  trail records who approved, and the page shows the new account value.
* **Change**: you say what should be different: remove a stock, set a smaller maximum per
  stock, or ask for less risk. The agents **re-plan immediately** with your change and ask
  you again.
* **Reject**: you say why. Nothing is traded, and the reason is remembered for next time.

**It learns.** If "Remember this" is ticked, your change is saved for that client. The next time
anyone asks for that client, the first plan already follows it, and the plan says so.

**It corrects itself.** When a check fails (a wrong number in the memo, a source that does not
support a sentence), the agent gets the list of problems and rewrites once. If it still fails,
it falls back to a safe answer. If the AI provider is failing, a "circuit breaker" stops calling
it for a minute and the safe answers are used straight away.

```
plan -> checks -> (rewrite if needed) -> you change it -> re-plan -> you approve
  ^                                                                   |
  +------------------- remembered for next time ---------------------+
```

**Is it getting better?** Every decision is recorded in Langfuse: whether you approved, how
many changes you asked for, how many preferences were used, how many checks failed and were
fixed. If the loop works, approvals go up and changes go down over time.

## 10. How it checks its own quality

* **RAGAS** is a standard toolkit for grading answers that come from documents. A second AI
  (the "judge") checks faithfulness (claims backed by sources), answer relevancy, context
  precision (useful sources first), and memo quality.
* **Simple checks** without AI: does every sentence cite a source? Does every number appear in
  a source? Were the client's rules read correctly? Does the plan pass every rule?
* **Langfuse** is a dashboard that records every step of every run (each agent, each tool, each
  AI call, each safety check, its cost and time) and all the scores. Personal data is masked
  out before anything is sent to it.

## 11. Using the app

Open the app (for example http://localhost:3000).

**Your input (home page)**

1. **Who is the portfolio for?** Pick one of four example clients (three US, one Indian), or
   one you added. Each card shows the key rules; **Read the rules** lists every rule with the
   sentence of the policy it comes from. Under the cards you see what the team remembers about
   the client.
2. **What should the agents do?** Type a request, or click an example.
3. Press **Start**. It takes about 20 seconds.

**Adding your own client**

Press **Add a client** (the dashed card). Fill in:

* who the client is and the market (US or India);
* the goal, which fills in typical rules you can change;
* the cash and the shares they already own;
* the rules: number of stocks, most and least per stock, most per sector, largest yearly ups
  and downs, risk level, sectors and companies not allowed;
* notes, if any.

On the right you see the **policy document the agents will read**, updated as you type. If the
rules cannot work, it tells you why in plain words (for example "5 stocks of at most 15% each
cannot add up to 100%"). Press **Add client**: the client appears on the home page, ready for a
request. Clients you added can be removed; their past plans stay in History.

**What you get (run page)**

* **Progress bar** with five stages, and a line saying how many safety checks passed.
* **Your decision** box: "Why this plan" (your question, the rules ticked, the reason for each
  stock), the buy and sell list with a reason for each, then **Approve**, **Change**, **Reject**.
* Four tabs:
  * **Recommendation**: the plan in plain words, expected return and risk, what changes, the
    risks to know, and what was checked before you saw it.
  * **Research**: a short research report: a summary, then one section per company with its
    key numbers (taken straight from the filings), key points and risks, every sentence with a
    clickable source, and what the reports do not cover. **Download** saves it; **Print / PDF**
    makes a clean printout. The Recommendation tab has **Download client report** (memo, portfolio,
    rules and the research in one document).
  * **Checks**: every safety check, every client rule (and where it is written), and the
    quality scores.
  * **Details**: how the stocks were chosen, the money split, the back-test, what the team
    remembered, the audit trail, and every agent step.
* If a request is stopped by the safety check, you see why and nothing else runs.

## 12. Words used

| Word | Meaning |
|---|---|
| Portfolio | The group of shares someone owns |
| Rebalance | Buy and sell so the portfolio fits the plan and rules again |
| Volatility / risk | How much the value goes up and down |
| Back-test | Checking how the plan would have done on past days it did not see |
| Agent | An AI helper with one job |
| LLM | The AI language model that reads and writes text (here: gpt-oss-120b on Groq) |
| RAG | Answering from looked-up documents, with sources |
| Guardrail | A rule that checks what goes into or out of the AI |
| Prompt injection | Text that tries to give the AI secret orders |
| MCP | A standard way for agents to use tools |
| A2A | A standard way for agents to give each other tasks |
| RAGAS | A toolkit that grades document-based answers |
| Langfuse | A dashboard that records every step and score |

## 13. Limits

* It is a research and learning project: practice account only, **not investment advice**.
* The clients are made-up examples; the companies, reports and prices are real.
* The safety checks stop the attacks they were tested on, and most new ones, but no filter is
  perfect; the signed approval and the broker's limits are the final protection.
* A few months of back-test prove little about the future.
