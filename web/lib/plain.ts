// Plain-language wording for people who are not finance or quantum experts.

import type { RunStatus } from "./types";
import type { Tone } from "@/components/ui";

export const METHOD: Record<string, { name: string; short: string; color: string; explain: string }> = {
  classical: {
    name: "Normal computer",
    short: "Normal",
    color: "var(--series-classical)",
    explain: "Checks every possible combination of stocks, so its answer is proven to be the best.",
  },
  quantum: {
    name: "Quantum computer (simulated)",
    short: "Quantum",
    color: "var(--series-quantum)",
    explain: "QAOA, a quantum algorithm, run on a quantum simulator: one qubit per stock.",
  },
  hybrid: {
    name: "Quantum + normal together",
    short: "Hybrid",
    color: "var(--series-hybrid)",
    explain: "Starts from the quantum answer, then a normal computer tries small swaps to improve it.",
  },
  greedy: {
    name: "Simple rule of thumb",
    short: "Rule of thumb",
    color: "var(--series-greedy)",
    explain: "Just picks the stocks with the best return for their risk. A baseline for comparison.",
  },
  recommended: { name: "Recommended portfolio", short: "Recommended", color: "var(--accent)", explain: "" },
  current: {
    name: "Client's current portfolio",
    short: "Current",
    color: "var(--series-current)",
    explain: "What the client holds today.",
  },
  equal_weight: {
    name: "Equal amount in every allowed stock",
    short: "Equal split",
    color: "var(--series-greedy)",
    explain: "",
  },
  benchmark: { name: "The market index", short: "Market", color: "var(--series-spy)", explain: "S&P 500 (US) or Nifty 50 (India)." },
};

export const STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: "Starting", tone: "neutral" },
  running: { label: "Agents working", tone: "accent" },
  awaiting_approval: { label: "Waiting for your approval", tone: "warning" },
  executed: { label: "Approved · trades placed", tone: "good" },
  approved: { label: "Approved", tone: "good" },
  rejected: { label: "Rejected", tone: "neutral" },
  completed: { label: "Finished", tone: "good" },
  blocked: { label: "Blocked by a rule", tone: "critical" },
  failed: { label: "Something went wrong", tone: "critical" },
};

export const RULE_LABEL: Record<string, string> = {
  holdings: "Number of stocks",
  max_weight: "Largest single stock",
  min_weight: "Smallest position",
  max_sector_weight: "Largest industry share",
  excluded_sectors: "Industries the client excludes",
  excluded_tickers: "Companies the client excludes",
  max_volatility: "Risk limit (volatility)",
};

export const SCORE_GROUPS: { title: string; plain: string; names: string[] }[] = [
  {
    title: "Is the research answer trustworthy?",
    plain: "RAGAS scores, checked by an AI judge",
    names: ["rag_faithfulness", "rag_answer_relevancy", "rag_context_precision", "rag_context_relevance"],
  },
  {
    title: "Simple automatic checks",
    plain: "No AI needed",
    names: ["rag_citation_coverage", "rag_numeric_grounding", "output_rule_extraction_accuracy", "output_compliance_pass"],
  },
  {
    title: "Is the final memo good?",
    plain: "RAGAS rubric score",
    names: ["output_memo_quality"],
  },
  {
    title: "Quantum and portfolio",
    plain: "How the quantum computer and the portfolio did",
    names: ["quantum_optimality_gap", "quantum_feasible_probability", "quantum_approximation_ratio", "portfolio_oos_sharpe", "portfolio_oos_excess_return_vs_benchmark"],
  },
];

export const SCORE_LABEL: Record<string, { name: string; explain: string; kind: "unit" | "bool" | "gap" | "raw" | "pct" }> = {
  rag_faithfulness: { name: "Faithfulness", explain: "Every claim is backed by the filings", kind: "unit" },
  rag_answer_relevancy: { name: "Answer relevancy", explain: "It answers the question asked", kind: "unit" },
  rag_context_precision: { name: "Context precision", explain: "The useful sources were ranked first", kind: "unit" },
  rag_context_relevance: { name: "Context relevance", explain: "The sources fit the question", kind: "unit" },
  rag_citation_coverage: { name: "Sentences with a source", explain: "Share of sentences that cite a filing", kind: "unit" },
  rag_numeric_grounding: { name: "Numbers found in sources", explain: "Every number really appears in a filing", kind: "unit" },
  output_rule_extraction_accuracy: { name: "Rules read correctly", explain: "Client rules match the hand-checked answer key", kind: "unit" },
  output_compliance_pass: { name: "All rules pass", explain: "The portfolio obeys every client rule", kind: "bool" },
  output_memo_quality: { name: "Memo quality", explain: "Accurate, clear, honest about risks", kind: "unit" },
  quantum_optimality_gap: { name: "Quantum vs best", explain: "0% means quantum found the best answer", kind: "gap" },
  quantum_feasible_probability: { name: "Valid quantum answers", explain: "Share of quantum results that pick exactly the right number of stocks", kind: "unit" },
  quantum_approximation_ratio: { name: "Quantum quality", explain: "1.0 would be perfect", kind: "unit" },
  portfolio_oos_sharpe: { name: "Return per unit of risk", explain: "Sharpe ratio on unseen recent months", kind: "raw" },
  portfolio_oos_excess_return_vs_benchmark: { name: "vs the market", explain: "Return minus the market index, unseen months", kind: "pct" },
  rag_top_rerank_score: { name: "Best source match", explain: "Reranker confidence", kind: "raw" },
};

export const DOC_LABEL: Record<string, string> = {
  risk_factors: "10-K · Risk factors (SEC)",
  mdna: "10-K · Management discussion (SEC)",
  ar_mdna: "Annual report · Management discussion (SEBI)",
  ar_risk: "Annual report · Risks",
  brsr: "BRSR sustainability report (SEBI)",
  facts: "Reported financials",
  mandate: "Client rules",
};

export const MARKET_LABEL: Record<string, { flag: string; name: string }> = {
  US: { flag: "US", name: "United States · NYSE/Nasdaq" },
  IN: { flag: "IN", name: "India · NSE" },
};

/** The five stages a person sees, built from the twelve agent steps. */
export const STAGES: { key: string; title: string; steps: string[] }[] = [
  { key: "understand", title: "Understand", steps: ["intake"] },
  { key: "research", title: "Research", steps: ["research", "risk", "mandate"] },
  { key: "choose", title: "Choose stocks", steps: ["optimize", "backtest"] },
  { key: "check", title: "Check & explain", steps: ["check", "report", "evaluate", "trades"] },
  { key: "decide", title: "Your decision", steps: ["approval", "execute"] },
];
