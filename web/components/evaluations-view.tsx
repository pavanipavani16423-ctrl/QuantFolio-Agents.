"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Accent, Badge, Card, EmptyState, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct, seconds } from "@/lib/format";

interface RagEval {
  created: string;
  dataset: { name: string; items: number; by_kind: Record<string, number>; source: string };
  k: number;
  modes: Record<string, Record<string, number | null>>;
  llm: { judge: string | null; metrics: Record<string, Record<string, number | null>> | null };
  langfuse: { dataset: string | null; runs: { mode: string; url: string | null }[] };
  notes: string[];
}

interface QuantumCase {
  client: string;
  n: number;
  k: number;
  mixer: string;
  reps: number;
  gap: number;
  found_optimum: boolean;
  approximation_ratio: number | null;
  optimal_probability: number | null;
  feasible_probability: number | null;
  seconds: number;
  classical_seconds: number;
  after_local_search_gap: number;
}

interface QuantumEval {
  created: string;
  cases: QuantumCase[];
  summary: Record<string, Record<string, number>>;
  notes: string[];
}

const MODE_LABEL: Record<string, string> = {
  bm25: "Keyword only (BM25)",
  dense: "Meaning only (embeddings)",
  hybrid: "Hybrid (RRF fusion)",
  hybrid_rerank: "Hybrid + reranker",
};

const SHORT_LABEL: Record<string, string> = {
  bm25: "Keyword",
  dense: "Meaning",
  hybrid: "Hybrid",
  hybrid_rerank: "Hybrid + rerank",
};

const axis = { stroke: "var(--subtle-foreground)", fontSize: 11, tickLine: false, axisLine: false } as const;

function RetrievalChart({ data, metric }: { data: RagEval; metric: string }) {
  const rows = Object.entries(data.modes).map(([mode, m]) => ({ mode: SHORT_LABEL[mode] ?? mode, value: m[metric] ?? 0 }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 24, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="mode" {...axis} interval={0} tick={{ fontSize: 11 }} />
          <YAxis {...axis} domain={[0, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
          <Tooltip formatter={(v) => pct(Number(v))} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }} />
          <Bar dataKey="value" fill="var(--accent)" radius={[8, 8, 0, 0]} isAnimationActive={false}>
            <LabelList dataKey="value" position="top" formatter={(v) => pct(Number(v), 0)} style={{ fontSize: 11, fill: "var(--foreground)" }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EvaluationsView() {
  const [data, setData] = useState<{ rag_eval?: RagEval; quantum_eval?: QuantumEval } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api.evaluations().then((d) => setData(d as never)).catch(() => setError(true));
  }, []);

  if (error) return <div className="mt-16"><EmptyState>The backend is not reachable.</EmptyState></div>;
  if (!data) return <div className="grid place-items-center py-24 text-muted-foreground"><Loader2 className="size-5 animate-spin" /></div>;

  const rag = data.rag_eval;
  const q = data.quantum_eval;
  return (
    <div className="mt-16 flex flex-col gap-24">
      <section>
        <SectionHeading
          eyebrow="Search quality"
          title={
            <>
              Does hybrid search <Accent>find the right passage</Accent>?
            </>
          }
          lead={
            rag
              ? `${rag.dataset.items} test questions with a known correct passage (${Object.entries(rag.dataset.by_kind).map(([k, v]) => `${v} ${k}`).join(", ")}). Each search mode answers all of them; we count how often the right passage is in the top ${rag.k}.`
              : undefined
          }
        />
        {rag ? (
          <>
            <div className="mt-10 grid gap-4 lg:grid-cols-2">
              <Card>
                <h3 className="font-semibold">Right passage found in the top {rag.k} (hit rate)</h3>
                <RetrievalChart data={rag} metric={`hit_rate@${rag.k}`} />
              </Card>
              <Card>
                <h3 className="font-semibold">RAGAS context recall (ID-based)</h3>
                <RetrievalChart data={rag} metric="ragas_id_context_recall" />
              </Card>
            </div>
            <div className="mt-4 overflow-x-auto rounded-3xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-panel-2 text-left text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Search mode</th>
                    {Object.keys(Object.values(rag.modes)[0]).map((m) => (
                      <th key={m} className="px-4 py-2 font-medium">{m}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(rag.modes).map(([mode, metrics]) => (
                    <tr key={mode} className="border-t">
                      <td className="px-4 py-2 font-medium">{MODE_LABEL[mode] ?? mode}</td>
                      {Object.entries(metrics).map(([k, v]) => (
                        <td key={k} className="tabular px-4 py-2">
                          {v === null ? "–" : k.includes("latency") ? `${Math.round(v)} ms` : num(v, 3)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rag.llm.metrics ? (
              <div className="mt-4 overflow-x-auto rounded-3xl border bg-card">
                <p className="px-4 pt-4 text-sm font-semibold">RAGAS LLM-judged metrics (judge: {rag.llm.judge})</p>
                <table className="mt-2 w-full text-sm">
                  <tbody>
                    {Object.entries(rag.llm.metrics).map(([mode, metrics]) => (
                      <tr key={mode} className="border-t">
                        <td className="px-4 py-2 font-medium">{MODE_LABEL[mode] ?? mode}</td>
                        {Object.entries(metrics).map(([k, v]) => (
                          <td key={k} className="tabular px-4 py-2">
                            <span className="text-xs text-muted-foreground">{k}</span> {v === null ? "–" : num(v, 3)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">
                LLM-judged RAGAS metrics (faithfulness, factual correctness) appear here once a Groq key is configured and
                the evaluation script is re-run.
              </p>
            )}
            {rag.langfuse.runs.some((r) => r.url) && (
              <div className="mt-4 flex flex-wrap gap-2">
                {rag.langfuse.runs.filter((r) => r.url).map((r) => (
                  <a key={r.mode} href={r.url!} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-sm hover:bg-panel">
                    Langfuse experiment: {MODE_LABEL[r.mode] ?? r.mode} <ExternalLink className="size-3.5" />
                  </a>
                ))}
              </div>
            )}
            <ul className="mt-4 list-disc pl-5 text-sm text-muted-foreground">
              {rag.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </>
        ) : (
          <div className="mt-10"><EmptyState>Run <code>uv run python scripts/eval_rag.py</code> to create this report.</EmptyState></div>
        )}
      </section>

      <section>
        <SectionHeading
          eyebrow="Quantum"
          title={
            <>
              Quantum vs the <Accent>exact answer</Accent>.
            </>
          }
          lead="For each client, the quantum algorithm (QAOA) chooses the stocks and is compared with an exhaustive search that is guaranteed to be optimal. Two quantum designs are tested: the standard one and one that can only produce valid answers (XY mixer)."
        />
        {q ? (
          <>
            <div className="mt-10 overflow-x-auto rounded-3xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-panel-2 text-left text-muted-foreground">
                  <tr>
                    {["Client", "Qubits", "Pick", "Quantum design", "Layers", "Gap to best", "Valid answers", "P(best)", "Quality ratio", "Quantum time", "Exact time", "After swaps"].map((h) => (
                      <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.cases.map((c, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-3 py-2 font-medium">{c.client}</td>
                      <td className="tabular px-3 py-2">{c.n}</td>
                      <td className="tabular px-3 py-2">{c.k}</td>
                      <td className="px-3 py-2">{c.mixer === "xy" ? "XY (valid only)" : "Standard (X)"}</td>
                      <td className="tabular px-3 py-2">{c.reps}</td>
                      <td className="px-3 py-2">
                        <Badge tone={c.found_optimum ? "good" : c.gap < 0.05 ? "warning" : "critical"}>{c.found_optimum ? "0% ✓" : pct(c.gap)}</Badge>
                      </td>
                      <td className="tabular px-3 py-2">{pct(c.feasible_probability, 0)}</td>
                      <td className="tabular px-3 py-2">{pct(c.optimal_probability, 2)}</td>
                      <td className="tabular px-3 py-2">{num(c.approximation_ratio, 3)}</td>
                      <td className="tabular px-3 py-2">{seconds(c.seconds)}</td>
                      <td className="tabular px-3 py-2">{seconds(c.classical_seconds)}</td>
                      <td className="tabular px-3 py-2">{pct(c.after_local_search_gap)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-4 list-disc pl-5 text-sm text-muted-foreground">
              {q.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </>
        ) : (
          <div className="mt-10"><EmptyState>Run <code>uv run python scripts/quantum_experiment.py</code> to create this report.</EmptyState></div>
        )}
      </section>
    </div>
  );
}
