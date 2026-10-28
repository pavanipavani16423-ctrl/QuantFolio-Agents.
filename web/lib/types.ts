// TypeScript mirrors of the backend's run document (app/services/runs.py).

export type StepStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface Step {
  key: string;
  number: number;
  title: string;
  status: StepStatus;
  summary?: string | null;
  error?: string | null;
  seconds?: number;
  attempt?: number;
  started_at?: string;
}

export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "executed"
  | "approved"
  | "rejected"
  | "completed"
  | "blocked"
  | "failed";

export interface Source {
  n: number;
  chunk_id: string;
  doc_id: string;
  doc_type: string;
  ticker: string | null;
  title: string;
  section: string;
  source_url: string | null;
  text: string;
  rerank_score: number | null;
  bm25_rank: number | null;
  dense_rank: number | null;
}

export interface KeyFigures {
  ticker: string;
  company: string;
  fiscal_year: number;
  period_end: string;
  items: { label: string; value: string; note?: string }[];
  source: string;
  source_url: string | null;
}

export interface CompanyFindings {
  ticker: string;
  key_points: string[];
  risks: string[];
}

export interface Research {
  question: string;
  answer: string;
  companies?: CompanyFindings[];
  not_covered?: string[];
  key_figures?: KeyFigures[];
  risk_flags: { ticker: string; risk: string; source: number }[];
  sources: Source[];
  queries: string[];
  method: string;
  retrieval_mode: string;
  quarantined?: { chunk_id: string; ticker: string | null; title: string; signals: string[] }[];
  guardrails?: Guardrail[];
  self_corrections?: number;
  cache?: { similarity: number; question: string; run_id: string | null; when: string } | null;
}

export type Verdict = "pass" | "warn" | "fixed" | "block";

export interface Guardrail {
  layer: "input" | "retrieval" | "memory" | "output" | "action";
  check: string;
  verdict: Verdict;
  detail: string;
  step?: string;
  revision?: number;
}

export interface Memory {
  semantic: Preference[];
  procedural: Preference[];
  episodic: { run_id: string; outcome: "approved" | "rejected" | "changed"; summary: string; when: string; created_at: string | null }[];
  quarantined: Guardrail[];
  counts?: { episodic: number; semantic: number; procedural: number };
  research_cache_entries?: number;
}

export interface AuditEntry {
  seq: number;
  at: string;
  run_id: string | null;
  client_id: string | null;
  actor: string;
  action: string;
  details: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface Rules {
  client_id: string;
  holdings: number;
  max_weight: number;
  min_weight: number;
  max_sector_weight: number;
  max_volatility: number;
  risk_aversion: number;
  excluded_sectors: string[];
  excluded_tickers: string[];
  approval_required: boolean;
  citations: { rule: string; chunk_id: string; quote: string }[];
}

export interface Proposal {
  method: "optimal" | "baseline";
  label: string;
  selected: string[];
  weights: Record<string, number>;
  expected_return: number;
  volatility: number;
  utility: number;
  selection_utility: number;
  seconds: number;
  feasible: boolean;
  volatility_limit_met: boolean;
  details: { sector_weights: Record<string, number>; weight_status: string };
}

export interface Optimization {
  problem: { tickers: string[]; k: number; risk_aversion: number };
  candidates: number;
  combinations?: number;
  errors: Record<string, string>;
  search: { subsets_evaluated: number | null; feasible_subsets?: number; optimality: string; swap_moves?: number };
  baseline_gap?: number;
  proposals: Record<string, Proposal>;
  recommended: string;
}

export interface BacktestMetrics {
  total_return: number;
  annualized_return: number;
  annualized_volatility: number;
  sharpe_ratio: number | null;
  max_drawdown: number;
}

export interface Backtest {
  start: string;
  end: string;
  days: number;
  method: string;
  metrics: Record<string, BacktestMetrics>;
  dates: string[];
  curves: Record<string, number[]>;
}

export interface RuleCheck {
  rule: string;
  passed: boolean;
  detail: string;
  citation: string | null;
}

export interface Memo {
  headline: string;
  summary: string;
  key_changes: string[];
  risks: string[];
  method: string;
  self_corrections?: number;
}

export interface Score {
  value: number;
  comment: string | null;
  source: "ragas" | "deterministic";
}

export interface Trade {
  ticker: string;
  side: "buy" | "sell";
  shares: number;
  price: number;
  value: number;
  weight_before: number;
  weight_after: number;
}

export interface RunResult {
  input_guard?: { verdict: Verdict; blocked: boolean; reason: string | null };
  memory?: Memory;
  intake?: { client_id: string; research_question: string; focus_tickers: string[]; method: string };
  research?: Research;
  risk_profile?: {
    tickers: string[];
    volatility: Record<string, number>;
    expected_return: Record<string, number>;
    beta: Record<string, number>;
    sectors: Record<string, string>;
    window: { start: string; end: string; observations: number };
    notes: string[];
  };
  rules?: Rules;
  mandate_meta?: { method: string; notes: string[]; retrieved_chunks: string[]; quarantined?: { chunk_id: string }[] };
  optimization?: Optimization;
  backtest?: Backtest;
  compliance?: { passed: boolean; checks: RuleCheck[] };
  risk_check?: {
    volatility: number;
    beta: number;
    var95_1d: number;
    cvar95_1d: number;
    max_drawdown: number;
    warnings: string[];
    within_limit: boolean;
  };
  memo?: Memo;
  evaluation?: {
    scores: Record<string, Score>;
    judge: string | null;
    notes: string[];
    ragas_status?: "running" | "done" | "failed" | "off";
  };
  preferences?: Preference[];
  applied?: { removed: string[]; max_weight: number | null; lower_risk: number; notes: string[]; sources: string[] };
  effective_rules?: Rules;
  revision?: number;
  trades?: {
    trades: Trade[];
    turnover: number;
    cash_after: number;
    account_value: number;
    price_date: string;
    limits?: { check: string; passed: boolean; detail: string }[];
    allowed?: boolean;
  };
  approval?: { approved: boolean; action?: string; reviewer: string; note: string | null };
  execution?: {
    approval_id?: string;
    approved_by?: string;
    fills: { ticker: string; side: string; shares: number; price: number; value: number }[];
    account: { market_value: number; cash: number; positions: Record<string, number> };
  };
}

export interface ToolCall {
  agent: string;
  server: string;
  tool: string;
  status: string;
  latency_ms: number;
  attempt?: number;
  error?: string;
  via?: string;
  started_at?: string;
}

export interface Preference {
  id: number;
  client_id: string;
  kind: "exclude_ticker" | "max_weight" | "lower_risk" | "note";
  value: string;
  reason: string | null;
  reviewer: string | null;
  run_id: string | null;
  created_at: string | null;
}

export interface ChangeRequest {
  remove_tickers: string[];
  max_weight: number | null;
  lower_risk: boolean;
}

export interface Run {
  id: string;
  client_id: string;
  client_name: string;
  profile: string;
  market: "US" | "IN";
  market_name: string;
  currency: string;
  currency_symbol: string;
  benchmark_name: string;
  research_sources: string;
  feedback: { action: string; reviewer: string; note: string | null; changes: ChangeRequest | null }[];
  request: string;
  pii_redacted?: Record<string, number>;
  status: RunStatus;
  blocked_reason?: string | null;
  created_at: string;
  updated_at: string;
  trace_id: string | null;
  trace_url: string | null;
  error: string | null;
  llm: string;
  langfuse: boolean;
  steps: Record<string, Step>;
  decisions: { next: string[]; reason: string; at: string }[];
  tool_calls: ToolCall[];
  llm_calls: { agent: string; status: string; model?: string; latency_ms?: number; via?: string }[];
  a2a_calls: { agent: string; url: string; transport: string; skill: string; card: string | null }[];
  guardrails?: Guardrail[];
  result: RunResult;
}

export interface RunSummary {
  id: string;
  client_id: string;
  client_name: string;
  profile: string;
  request: string;
  status: RunStatus;
  created_at: string;
  trace_url: string | null;
  llm: string;
  market?: string;
  currency_symbol?: string;
  recommended: string | null;
  blocked_reason?: string | null;
}

export interface Client {
  client_id: string;
  name: string;
  profile: string;
  mandate_doc: string;
  market_value: number;
  holdings: number;
  price_date: string;
  market: "US" | "IN";
  market_name: string;
  currency: string;
  currency_symbol: string;
  benchmark_name: string;
  research_sources: string;
  who: string;
  rules_summary: string;
  examples: string[];
  custom: boolean;
}

export interface NewClient {
  name: string;
  who: string;
  market: "US" | "IN";
  goal: "income" | "balanced" | "growth" | "esg";
  risk: "low" | "medium" | "high";
  horizon_years: number;
  holdings: number;
  max_weight: number;
  min_weight: number;
  max_sector_weight: number;
  max_volatility: number;
  excluded_sectors: string[];
  excluded_tickers: string[];
  cash: number;
  positions: Record<string, number>;
  notes: string;
}

export interface ClientRules {
  client_id: string;
  title: string;
  rules: Rules;
  names: Record<string, string>;
}
