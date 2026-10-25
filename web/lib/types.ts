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

export interface Research {
  question: string;
  answer: string;
  risk_flags: { ticker: string; risk: string; source: number }[];
  sources: Source[];
  queries: string[];
  method: string;
  retrieval_mode: string;
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
  method: "classical" | "quantum" | "hybrid" | "greedy";
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

export interface QuantumInfo {
  num_qubits: number;
  reps: number;
  shots: number;
  optimizer: string;
  backend: string;
  circuit_depth: number;
  two_qubit_gates: number;
  gate_counts: Record<string, number>;
  iterations: number;
  optimal_parameters: Record<string, number>;
  approximation_ratio: number | null;
  feasible_approximation_ratio: number | null;
  optimal_probability: number | null;
  feasible_probability: number | null;
  feasible_sample_fraction: number | null;
  mixer: string;
  hamming_weight: number | null;
  execution_time: number;
  timings: { optimize_seconds: number; sample_seconds: number };
  convergence: number[];
  top_samples: { bitstring: string; probability: number; feasible: boolean }[];
}

export interface Optimization {
  problem: { tickers: string[]; k: number; risk_aversion: number };
  qubits: number;
  errors: Record<string, string>;
  classical: { subsets_evaluated: number; feasible_subsets: number; optimality: string };
  quantum?: QuantumInfo;
  hybrid?: { swap_moves: number; repaired: boolean; start_utility: number };
  quantum_gap?: number;
  quantum_found_optimum?: boolean;
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
  quantum_note: string;
  method: string;
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
  mandate_meta?: { method: string; notes: string[]; retrieved_chunks: string[] };
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
  evaluation?: { scores: Record<string, Score>; judge: string | null; notes: string[] };
  trades?: { trades: Trade[]; turnover: number; cash_after: number; account_value: number; price_date: string };
  approval?: { approved: boolean; reviewer: string; note: string | null };
  execution?: {
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

export interface Run {
  id: string;
  client_id: string;
  client_name: string;
  profile: string;
  request: string;
  methods: string[];
  status: RunStatus;
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
  recommended: string | null;
  quantum_gap: number | null;
}

export interface Client {
  client_id: string;
  name: string;
  profile: string;
  mandate_doc: string;
  market_value: number;
  holdings: number;
  price_date: string;
}
