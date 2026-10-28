"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Accent, Card, EmptyState, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";
import { num, pct } from "@/lib/format";

interface RagEval {
  created: string;
  dataset: { name: string; items: number; by_kind: Record<string, number>; source: string };
  k: number;
  modes: Record<string, Record<string, number | null>>;
  llm: { judge: string | null; metrics: Record<string, Record<string, number | null>> | null };
  langfuse: { dataset: string | null; runs: { mode: string; url: string | null }[] };
  notes: string[];
}

interface Rates {
  attack_block_rate: number | null;
  benign_pass_rate: number | null;
}

interface GuardrailEval {
  created: string;
  counts: Record<string, number>;
  metrics: Record<string, number>;
  semantic_threshold: { calibrated: number; configured: number | null };
  stages: Record<string, { n: number; pattern_only: Rates; two_stage: Rates; misses: { id: string; kind: string; expect: string }[] }>;
  by_kind: Record<string, { n: number; correct: number }>;
}

interface TuningRow {
  hit_rate: number;
  mrr: number;
  recall: number;
  latency_ms: number;
  context_chars: number;
  [key: string]: unknown;
}

interface RagTuning {
  created: string;
  items: number;
  stages: Record<string, TuningRow[]>;
  best: { size: number[]; model: string; prefix: boolean; reranker: string; candidates: number; rerank_top: number; k: number };
}

const GUARD_METRIC: Record<string, string> = {
  attack_block_rate: "Attacks stopped",
  benign_pass_rate: "Normal requests allowed",
  pii_recall: "Personal data removed",
  pii_clean_untouched: "Financial text left alone",
  poisoned_passages_quarantined: "Poisoned passages set aside",
  clean_passages_kept: "Clean passages kept",
};

const STAGE_LABEL: Record<string, string> = {
  training: "Written with the rules",
  heldout_v1: "Held-out set 1",
  heldout_v2: "Held-out set 2 (clean test)",
};

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
  const [data, setData] = useState<{ rag_eval?: RagEval; rag_tuning?: RagTuning; guardrail_eval?: GuardrailEval } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api.evaluations().then((d) => setData(d as never)).catch(() => setError(true));
  }, []);

  if (error) return <div className="mt-16"><EmptyState>The backend is not reachable.</EmptyState></div>;
  if (!data) return <div className="grid place-items-center py-24 text-muted-foreground"><Loader2 className="size-5 animate-spin" /></div>;

  const rag = data.rag_eval;
  const g = data.guardrail_eval;
  const tune = data.rag_tuning;
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

      {tune && <TuningSection tune={tune} />}

      <section>
        <SectionHeading
          eyebrow="Safety"
          title={
            <>
              Red-team test of the <Accent>guardrails</Accent>.
            </>
          }
          lead="Attacks (hidden instructions, jailbreaks, insider trading, off-topic requests), tricky but normal requests, personal data, and real report passages with an instruction planted inside. Held-out sets were written after the rules and never used to tune them."
        />
        {g ? (
          <>
            <div className="mt-10 grid gap-3 sm:grid-cols-3">
              {Object.entries(g.metrics).map(([k, v]) => (
                <div key={k} className="rounded-2xl bg-panel-2 p-4">
                  <p className="text-xs text-muted-foreground">{GUARD_METRIC[k] ?? k}</p>
                  <p className="tabular mt-1 text-2xl font-semibold">{pct(v, 0)}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 overflow-x-auto rounded-3xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-panel-2 text-left text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Test set</th>
                    <th className="px-4 py-2 font-medium">Cases</th>
                    <th className="px-4 py-2 font-medium">Attacks stopped (patterns)</th>
                    <th className="px-4 py-2 font-medium">Attacks stopped (patterns + meaning)</th>
                    <th className="px-4 py-2 font-medium">Normal requests allowed</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(g.stages).map(([name, s]) => (
                    <tr key={name} className="border-t">
                      <td className="px-4 py-2 font-medium">{STAGE_LABEL[name] ?? name}</td>
                      <td className="tabular px-4 py-2">{s.n}</td>
                      <td className="tabular px-4 py-2">{pct(s.pattern_only.attack_block_rate, 0)}</td>
                      <td className="tabular px-4 py-2 font-semibold">{pct(s.two_stage.attack_block_rate, 0)}</td>
                      <td className="tabular px-4 py-2">{pct(s.two_stage.benign_pass_rate, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              Rules catch the attacks they were written for; the meaning check (similarity to known attack types) catches
              many reworded ones. Neither is perfect, which is why trades also need your signed approval and pass hard
              broker limits whatever the AI says.
            </p>
          </>
        ) : (
          <div className="mt-10"><EmptyState>Run <code>uv run python scripts/eval_guardrails.py</code> to create this report.</EmptyState></div>
        )}
      </section>
    </div>
  );
}

function TuningSection({ tune }: { tune: RagTuning }) {
  const best = tune.best;
  const tables: { key: string; title: string; label: (r: TuningRow) => string }[] = [
    { key: "A_chunk_size", title: "Chunk size", label: (r) => `${r.chunk_target} characters (${r.chunks} chunks) · ${SHORT_LABEL[String(r.mode)] ?? r.mode}` },
    { key: "B_embedding", title: "Embedding model", label: (r) => `${String(r.embedding).split("/")[1]}${r.query_prefix ? " + instruction" : ""} · ${SHORT_LABEL[String(r.mode)] ?? r.mode}` },
    { key: "C_reranker", title: "Reranker", label: (r) => String(r.reranker).split("/")[1] },
    { key: "D_depth", title: "Candidates, rerank depth, top-k", label: (r) => `${r.candidates} candidates · rerank ${r.rerank_top} · top ${r.k}` },
  ];
  return (
    <section>
      <SectionHeading
        eyebrow="Search settings"
        title={
          <>
            Every setting <Accent>chosen by measurement</Accent>.
          </>
        }
        lead={`Each choice was tested on the ${tune.items} labelled questions, one stage at a time. Chosen: ${best.size[0]}-character chunks, ${best.model.split("/")[1]}${best.prefix ? " with its search instruction" : ""}, ${best.reranker.split("/")[1]} reranking the top ${best.rerank_top} of ${best.candidates} candidates, ${best.k} passages per answer.`}
      />
      <div className="mt-10 grid gap-4 lg:grid-cols-2">
        {tables.map(({ key, title, label }) =>
          tune.stages[key] ? (
            <Card key={key} className="p-5">
              <h3 className="font-semibold">{title}</h3>
              <table className="mt-3 w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 font-medium">Setting</th>
                    <th className="py-1 font-medium">Found</th>
                    <th className="py-1 font-medium">MRR</th>
                    <th className="py-1 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {tune.stages[key].map((r, i) => (
                    <tr key={i} className="border-t">
                      <td className="py-1.5 pr-2 text-xs">{label(r)}</td>
                      <td className="tabular py-1.5">{pct(r.hit_rate, 1)}</td>
                      <td className="tabular py-1.5">{num(r.mrr, 3)}</td>
                      <td className="tabular py-1.5 text-xs">{Math.round(r.latency_ms)} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null,
        )}
      </div>
    </section>
  );
}
