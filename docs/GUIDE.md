# QuantFolio Agents, explained simply

A short guide for anyone who wants to understand this project. No finance or computer science
background needed.

---

## 1. What is it?

QuantFolio Agents is a **team of AI helpers that does a money manager's job**.

Imagine a family or a charity that has its savings invested in company shares. They have
rules, for example:

* "Hold exactly 8 companies."
* "No more than 20% of the money in one company."
* "No oil and gas companies."
* "Do not take too much risk."

Every few months someone has to check those shares: read the companies' annual reports,
decide what to buy and sell, check every rule, and explain the decision. That takes a person
hours. This project does it in about a minute, shows every reason, and **waits for a person
to approve** before anything is bought or sold.

It works for **US companies** (20 large ones like Apple, Microsoft, JPMorgan) and **Indian
companies** (18 large ones like Reliance, TCS, HDFC Bank, Infosys). All trades go to a
**practice account**: no real money ever moves.

## 2. Who is it useful for?

* **Financial advisors and portfolio managers** who look after many clients and must explain
  every change in plain language.
* **Compliance teams** who must prove that every client rule was read correctly and checked.
* **Students and researchers** who want to see how AI agents, document search and quantum
  computing work together on a real business problem.

## 3. How it works, end to end

```
You ask  ->  agents research  ->  agents choose stocks  ->  agents check  ->  YOU decide  ->  it learns
```

1. **You pick a client and type a request**, for example *"Rebalance the GreenLeaf endowment.
   What climate risks do NVIDIA and NextEra disclose?"*
2. **It understands the request**: which client, which question, which companies you mean.
   It also recalls what it learned from your earlier reviews of this client.
3. **Three agents work at the same time:**
   * one **reads the companies' official reports** and answers your question with sources;
   * one **measures how risky each share is** from two years of real prices;
   * one **reads the client's rules document** and turns it into exact limits.
4. **It chooses the stocks**: a normal computer and a (simulated) quantum computer each try to
   find the best group of stocks, and the results are compared.
5. **It checks the plan**: tests it on the most recent months of prices (which it did not see
   while planning), checks every rule again, writes a plain-language memo, and scores its own
   answer for quality.
6. **You decide**: Approve, Change or Reject.
7. **It learns**: if you change something, it re-plans straight away and remembers your
   preference for this client next time.

## 4. The agents (the "team")

An **agent** is an AI helper with one job. A **supervisor** decides who works next, like a
team lead.

| Agent | Its job, in plain words |
|---|---|
| Supervisor | Decides which agent works next; runs independent work at the same time; sends work back if a rule fails. |
| Intake agent | Reads your request: client, question, companies; recalls learned preferences. |
| Research agent | Searches the companies' reports and answers with numbered sources you can click. |
| Risk agent | Measures how much each share's price jumps around, and how risky the final plan is. |
| Compliance agent | Reads the client's rules document, turns it into exact limits, and checks the plan against every one. |
| Optimizer agent | Chooses the stocks and how much money goes into each: normal vs quantum vs both. |
| Report writer | Writes the recommendation in plain language. |
| Quality judge | Grades the answer (are the claims backed by sources? does it answer the question?). |
| Trader agent | Prepares the buy and sell orders, and places them after you approve (practice account). |

The **risk** and **compliance** agents run as separate services, as if they belonged to other
teams in a bank. They talk to the rest using **A2A** (agent-to-agent), an open standard for AI
agents to send each other tasks. Each one publishes an "Agent Card" that says what it can do.

## 5. The tools (MCP)

Agents do not touch data directly. They use **tools**, and the tools are offered through
**MCP** (Model Context Protocol), a standard way to connect AI agents to tools, like a shared
toolbox with labels. Each agent may only use the tools its job needs (a research agent cannot
place trades).

| Tool server | What is inside |
|---|---|
| Market data | Share prices, risk statistics, the market index |
| Research | The document search (see hybrid RAG below) |
| Optimizer | Stock choosing (normal, quantum, hybrid), money split, back-test |
| Paper broker | The practice account: see positions, prepare orders, place approved orders |

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

**Which documents?** It depends on the country, because each country requires different
reports:

| | United States | India |
|---|---|---|
| Regulator | SEC | SEBI |
| Documents | Form 10-K: "Risk factors" and "Management's discussion" | Annual report: "Management Discussion and Analysis" and its risk section; BRSR (sustainability report) |
| Numbers | SEC financial facts, in US dollars | Reported financials, in ₹ crore |
| Market index | S&P 500 | Nifty 50 |

Tested on 78 questions with known answers (US and India), meaning search found the right
passage most often (96%), keyword search failed on questions worded differently, and the
reranker put the right passage first most often. For the Indian questions, the default search
found the right passage every time.

## 7. Where quantum computing fits, and why it is useful

**The problem.** Choosing 10 stocks out of 20 has **184,756 possible combinations**. With more
stocks or more rules, the number of combinations explodes. This kind of "pick the best
combination" problem appears everywhere: portfolios, delivery routes, timetables.

**Why quantum.** Each stock is a yes/no choice, and a **qubit** (quantum bit) is a natural
yes/no unit. A quantum algorithm called **QAOA** treats all combinations at once and nudges
the good ones to become more likely. In the long run, quantum computers are expected to help
with very large combination problems that normal computers find too slow.

**How it is used here.**

* One qubit per stock: 17 to 20 qubits.
* The quantum circuit is built so it can only produce valid answers (exactly the number of
  stocks the client wants). This design choice made the biggest difference.
* It runs on a **quantum simulator** on a normal laptop (Qiskit), because real quantum
  hardware is not needed for this size.
* A **normal computer checks every combination** too, so the quantum answer can be graded
  against the proven best answer.
* A **hybrid** step lets a normal computer polish the quantum answer with small swaps.

**What we found, honestly.** At the default setting the quantum version found the proven
best portfolio for 3 of the 4 clients; for the Indian client (the hardest problem) it came
within about 10%. The hybrid polish step reached the best answer every time. At this small
size the normal computer is **faster and exact**, so the project does **not** claim quantum is better
today. Its value is showing *how* a quantum optimizer plugs into a real AI system, and
measuring it fairly, ready for bigger problems and better hardware.

## 8. Human in the loop, and how it improves itself

Nothing is traded without a person. When the plan is ready, you see the buy and sell list and
three buttons:

* **Approve**: the practice trades are placed.
* **Change**: you say what should be different: remove a stock, set a smaller maximum per
  stock, or ask for less risk. The agents **re-plan immediately** with your change and ask
  you again.
* **Reject**: you say why. Nothing is traded.

**It learns.** If "Remember this" is ticked, your change is saved as a preference for that
client. The next time anyone asks for that client, the first plan already follows it
(for example "avoid NVIDIA", "max 15% per stock"), and the plan says so. Preferences can only
make the rules stricter, never looser, and can be removed again.

**Is it getting better?** Every decision is recorded in Langfuse: whether you approved, how
many changes you asked for, and how many learned preferences were used. If the loop works,
approvals go up and changes go down over time.

```
plan -> you change it -> re-plan -> you approve
  ^                                        |
  +------ remembered for next time --------+
```

## 9. How it checks its own quality

* **RAGAS** is a standard toolkit for grading answers that come from documents. A second AI
  (the "judge") checks:
  * *faithfulness*: is every claim backed by the sources?
  * *answer relevancy*: does it answer the question asked?
  * *context precision*: were the useful sources ranked first?
  * *memo quality*: is the final memo accurate, clear and honest?
* **Simple checks** without AI: does every sentence cite a source? Does every number appear in
  a source? Were the client's rules read correctly? Does the plan pass every rule?
* **Langfuse** is a dashboard that records every step of every run (each agent, each tool,
  each AI call, its cost and time) and all the scores, so quality can be tracked over time.

## 10. Using the app

Open the app (for example http://localhost:3000).

**Your input (home page)**

1. **Who is the portfolio for?** Pick one of four example clients (three US, one Indian). Each
   card shows the key rules. "Read this client's rules" opens their rules document.
2. **What should the agents do?** Type a request, or click an example. You can name any of
   the companies, for example *"What risks do Reliance and TCS report?"*
3. Press **Start**. It takes about a minute.

**What you get (run page)**

* **Progress bar** with five stages: Understand, Research, Choose stocks, Check & explain,
  Your decision.
* **Your decision** box: the buy and sell list, with **Approve**, **Change**, **Reject**.
* Four tabs:
  * **Recommendation**: the plan in plain words, expected return and risk, what changes, the
    risks to know, and one line about the quantum result. If your feedback was used, it says
    so.
  * **Research**: the answer to your question with clickable sources; each source opens the
    exact passage and a link to the original report.
  * **Checks**: every client rule with a tick or a cross (and where the rule is written), and
    the quality scores.
  * **Details**: for experts: normal vs quantum comparison, how the money is split, the
    back-test chart, every agent step, and technical data.

**Other pages:** **History** (every past request) and **About** (how it works, and the test
results).

## 11. Words used

| Word | Meaning |
|---|---|
| Portfolio | The group of shares someone owns |
| Rebalance | Buy and sell so the portfolio fits the plan and rules again |
| Volatility / risk | How much the value goes up and down |
| Back-test | Checking how the plan would have done on past days it did not see |
| Agent | An AI helper with one job |
| LLM | The AI language model that reads and writes text (here: gpt-oss-120b on Groq) |
| RAG | Answering from looked-up documents, with sources |
| MCP | A standard way for agents to use tools |
| A2A | A standard way for agents to give each other tasks |
| Qubit | The yes/no unit of a quantum computer |
| QAOA | A quantum algorithm for "best combination" problems |
| RAGAS | A toolkit that grades document-based answers |
| Langfuse | A dashboard that records every step and score |

## 12. Limits

* It is a research and learning project: practice account only, **not investment advice**.
* The clients are made-up examples; the companies, reports and prices are real.
* The quantum computer is simulated, and at this size it is slower than a normal computer.
* A few months of back-test prove little about the future.
