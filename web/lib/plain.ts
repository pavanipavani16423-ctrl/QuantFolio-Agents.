// Plain-language wording for people who are not finance or AI experts.

import type { RunStatus } from "./types";
import type { Tone } from "@/components/ui";

export const METHOD: Record<string, { name: string; short: string; color: string; explain: string }> = {
  optimal: {
    name: "Best combination",
    short: "Best",
    color: "var(--series-classical)",
    explain: "Tries every possible combination of the allowed stocks, so the answer is proven to be the best.",
  },
  baseline: {
    name: "Simple rule of thumb",
    short: "Rule of thumb",
    color: "var(--series-greedy)",
    explain: "Just picks the stocks with the best return for their risk. Shows what the full search adds.",
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
    color: "var(--series-hybrid)",
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
  blocked: { label: "Stopped by a safety check", tone: "critical" },
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

export const SCORE_LABEL: Record<string, { name: string; explain: string; kind: "unit" | "bool" | "gap" | "raw" | "pct" }> = {
  rag_faithfulness: { name: "Faithfulness", explain: "Every claim is backed by the reports", kind: "unit" },
  rag_answer_relevancy: { name: "Answer relevancy", explain: "It answers the question asked", kind: "unit" },
  rag_context_precision: { name: "Context precision", explain: "The useful sources were ranked first", kind: "unit" },
  rag_context_relevance: { name: "Context relevance", explain: "The sources fit the question", kind: "unit" },
  rag_citation_coverage: { name: "Sentences with a source", explain: "Share of sentences that cite a report", kind: "unit" },
  rag_numeric_grounding: { name: "Numbers found in sources", explain: "Every number really appears in a report", kind: "unit" },
  output_rule_extraction_accuracy: { name: "Rules read correctly", explain: "Client rules match the hand-checked answer key", kind: "unit" },
  output_compliance_pass: { name: "All rules pass", explain: "The portfolio obeys every client rule", kind: "bool" },
  output_memo_quality: { name: "Memo quality", explain: "Accurate, clear, honest about risks", kind: "unit" },
  portfolio_oos_sharpe: { name: "Return per unit of risk", explain: "Sharpe ratio on unseen recent months", kind: "raw" },
  portfolio_oos_excess_return_vs_benchmark: { name: "vs the market", explain: "Return minus the market index, unseen months", kind: "pct" },
  portfolio_baseline_gap: { name: "Rule of thumb vs best", explain: "How far the simple rule falls short", kind: "gap" },
  rag_top_rerank_score: { name: "Best source match", explain: "Reranker confidence", kind: "raw" },
};

export const CHECK_LABEL: Record<string, string> = {
  personal_data: "Personal data removed",
  prompt_injection: "No hidden instructions",
  scope_policy: "Allowed request",
  indirect_injection: "Report passages are clean",
  mandate_injection: "Rules document is clean",
  note_injection: "Advisor note is safe to remember",
  research_citations_exist: "Every source number exists",
  research_citation_coverage: "Sentences cite a source",
  research_no_promises: "No promises in the research",
  citation_support: "Sources really say it",
  research_fallback: "Safe answer used",
  memo_no_promises: "No promises of returns",
  memo_numbers_grounded: "Numbers match the facts",
  memo_tickers_known: "Only stocks from the plan",
  memo_citations_exist: "Memo sources exist",
  memo_currency: "Right currency",
  memo_disclaimer: "Risk disclaimer included",
  memo_fallback: "Safe memo used",
  known_tickers: "Tradable stocks only",
  whole_shares: "Whole shares",
  no_short_selling: "No short selling",
  max_order_size: "No oversized order",
  max_turnover: "Turnover limit",
  max_orders: "Order count limit",
  approval_token: "Signed approval",
};

export const LAYER_LABEL: Record<string, { title: string; explain: string }> = {
  input: { title: "Your request", explain: "Checked before any AI sees it" },
  retrieval: { title: "Documents read", explain: "Passages that look like instructions are set aside" },
  memory: { title: "What it remembers", explain: "Notes are checked before they are reused" },
  output: { title: "The answer", explain: "Checked before you see it; fixed or replaced if needed" },
  action: { title: "The trades", explain: "Hard limits at the broker, and your signed approval" },
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

/** The five stages a person sees, built from the thirteen agent steps. */
export const STAGES: { key: string; title: string; steps: string[] }[] = [
  { key: "understand", title: "Understand", steps: ["guard", "intake"] },
  { key: "research", title: "Research", steps: ["research", "risk", "mandate"] },
  { key: "choose", title: "Choose stocks", steps: ["optimize", "backtest"] },
  { key: "check", title: "Check & explain", steps: ["check", "report", "evaluate", "trades"] },
  { key: "decide", title: "Your decision", steps: ["approval", "execute"] },
];

/** Risk level from the optimizer's risk-aversion setting (policies use 6 = low, 3-4 = medium, 2 = higher). */
export const riskWord = (riskAversion: number) => (riskAversion >= 6 ? "low" : riskAversion >= 3 ? "medium" : "higher");
