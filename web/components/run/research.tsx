"use client";

import { useEffect, useState } from "react";
import { Check, Download, ExternalLink, FileText, Printer, ShieldCheck, X } from "lucide-react";
import { download, researchMarkdown } from "@/lib/report";
import { Badge, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { pct } from "@/lib/format";
import { DOC_LABEL, RULE_LABEL } from "@/lib/plain";
import type { Run, Source } from "@/lib/types";
import { Cited } from "./recommendation";
import { RunSection } from "./section";


export function SourceDrawer({ source, onClose }: { source: Source | { chunk_id: string } | null; onClose: () => void }) {
  type Passage = { chunk_id: string; title: string; section: string; text: string; source_url: string | null };
  const [fetched, setFetched] = useState<Passage | null>(null);
  const needsFetch = source !== null && !("text" in source);
  const chunkId = source?.chunk_id;
  useEffect(() => {
    if (!needsFetch || !chunkId) return;
    let alive = true;
    api
      .chunk(chunkId)
      .then((c) => alive && setFetched(c))
      .catch(() => alive && setFetched({ chunk_id: chunkId, title: chunkId, section: "", text: "Could not load.", source_url: null }));
    return () => {
      alive = false;
    };
  }, [needsFetch, chunkId]);
  if (!source) return null;
  const full: Passage | null = "text" in source ? source : fetched?.chunk_id === source.chunk_id ? fetched : null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose} role="dialog" aria-modal>
      <aside className="h-full w-full max-w-xl overflow-auto bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            {"n" in source && <Badge tone="accent">Source {source.n}</Badge>}
            <h3 className="mt-2 font-semibold">{full?.title ?? "Loading…"}</h3>
            {full?.section && <p className="text-sm text-muted-foreground">{full.section}</p>}
          </div>
          <button onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-full hover:bg-panel" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{full?.text}</p>
        <p className="mt-4 text-xs text-subtle-foreground">Passage id: {source.chunk_id}</p>
        {"rerank_score" in source && (
          <p className="mt-1 text-xs text-subtle-foreground">
            Found by: keyword search rank {source.bm25_rank ?? "–"} · meaning search rank {source.dense_rank ?? "–"} · reranker score{" "}
            {source.rerank_score?.toFixed(2) ?? "–"}
          </p>
        )}
        {full?.source_url && (
          <a href={full.source_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
            Open the original document <ExternalLink className="size-3.5" />
          </a>
        )}
      </aside>
    </div>
  );
}

const METHOD_BADGE: Record<string, string> = {
  llm: "Written by AI, checked",
  memory: "Reused from research memory",
  rules: "Quotes from the reports (offline mode)",
  rules_after_llm_error: "Quotes from the reports (AI unavailable)",
  rules_after_guardrail: "Quotes from the reports (AI draft failed a check)",
  rules_circuit_open: "Quotes from the reports (AI unavailable)",
};

export function ResearchSection({ run, onCite }: { run: Run; onCite: (n: number) => void }) {
  const r = run.result.research;
  if (!r) return null;
  const figures = Object.fromEntries((r.key_figures ?? []).map((f) => [f.ticker, f]));
  const support = (r.guardrails ?? []).find((g) => g.check === "citation_support");
  const companies = r.companies?.length
    ? r.companies
    : (r.key_figures ?? []).map((f) => ({ ticker: f.ticker, key_points: [], risks: [] }));
  return (
    <RunSection
      id="research"
      eyebrow="Research report"
      title={r.question}
      lead={`Based only on the companies' own documents: ${run.research_sources ?? "annual reports"}. Click a number to read the exact passage.`}
      right={
        <div className="no-print flex flex-wrap items-center gap-2">
          <Badge tone={r.method === "llm" || r.method === "memory" ? "accent" : "neutral"}>{METHOD_BADGE[r.method] ?? r.method}</Badge>
          <button
            onClick={() => download(`research-${run.client_id}-${run.id}.md`, researchMarkdown(run))}
            className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-panel"
          >
            <Download className="size-3.5" /> Download
          </button>
          <button onClick={() => window.print()} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-panel">
            <Printer className="size-3.5" /> Print / PDF
          </button>
        </div>
      }
    >
      <div className="rounded-2xl bg-accent-soft/50 p-4">
        <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-accent">Summary</p>
        <p className="text-base leading-relaxed [overflow-wrap:anywhere]">
          <Cited text={r.answer} onCite={onCite} />
        </p>
        {support && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="size-3.5 text-good" /> {support.detail.split(":")[0]}
          </p>
        )}
      </div>

      <div className="mt-4 grid gap-3">
        {companies.map((c) => {
          const f = figures[c.ticker];
          return (
            <article key={c.ticker} className="rounded-2xl border p-4">
              <header className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-lg font-semibold">
                  {f?.company ?? c.ticker} <span className="text-sm font-normal text-muted-foreground">{c.ticker}</span>
                </h3>
                {f && <span className="text-xs text-subtle-foreground">Fiscal year {f.fiscal_year} · reported figures</span>}
              </header>
              {f && (
                <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {f.items.map((i) => (
                    <div key={i.label} className="rounded-xl bg-panel-2 px-3 py-2">
                      <dt className="text-[11px] text-muted-foreground">{i.label}</dt>
                      <dd className="tabular text-sm font-semibold">{i.value}</dd>
                      {i.note && <dd className="text-[10px] text-subtle-foreground">{i.note}</dd>}
                    </div>
                  ))}
                </dl>
              )}
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-sm font-semibold">Key points</p>
                  <ul className="flex flex-col gap-1.5 text-sm">
                    {c.key_points.length ? (
                      c.key_points.map((p) => (
                        <li key={p} className="leading-relaxed [overflow-wrap:anywhere]">
                          <Cited text={p} onCite={onCite} />
                        </li>
                      ))
                    ) : (
                      <li className="text-subtle-foreground">No passage on this in the sources.</li>
                    )}
                  </ul>
                </div>
                <div>
                  <p className="mb-1.5 text-sm font-semibold">Risks</p>
                  <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
                    {c.risks.length ? (
                      c.risks.map((p) => (
                        <li key={p} className="leading-relaxed [overflow-wrap:anywhere]">
                          <Cited text={p} onCite={onCite} />
                        </li>
                      ))
                    ) : (
                      <li className="text-subtle-foreground">No risk passage found.</li>
                    )}
                  </ul>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {r.not_covered && r.not_covered.length > 0 && (
        <div className="mt-4 rounded-2xl bg-panel-2 p-4">
          <p className="mb-1.5 text-sm font-semibold">Not covered by the sources</p>
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            {r.not_covered.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      <h3 className="mt-6 mb-2 text-sm font-semibold">Sources ({r.sources.length})</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {r.sources.map((s) => (
          <li key={s.chunk_id}>
            <button onClick={() => onCite(s.n)} className="flex w-full gap-3 rounded-2xl bg-panel-2 p-3 text-left hover:bg-panel">
              <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent-soft text-xs font-semibold text-accent">{s.n}</span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {s.ticker} · {DOC_LABEL[s.doc_type] ?? s.doc_type}
                </span>
                <span className="block truncate text-xs text-muted-foreground">{s.section || s.text.slice(0, 80)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs text-subtle-foreground">
        Hybrid search: keyword search (BM25) and meaning search (embeddings) are merged with reciprocal rank fusion,
        then a reranker model orders the best passages.
      </p>
    </RunSection>
  );
}

export function RulesSection({ run, onOpenChunk }: { run: Run; onOpenChunk: (chunkId: string) => void }) {
  const rules = run.result.rules;
  const compliance = run.result.compliance;
  const risk = run.result.risk_check;
  const applied = run.result.applied;
  if (!rules) return null;
  return (
    <RunSection
      id="rules"
      eyebrow="Client rules"
      title={compliance ? (compliance.passed ? "Every rule passes." : "A rule failed, so nothing is traded.") : "The client's rules"}
      lead="The compliance agent read these from the client's policy document and checked the final portfolio against each one."
    >
      {applied && applied.sources.length > 0 && (
        <p className="mb-3 rounded-2xl bg-accent-soft p-3 text-sm">
          <span className="font-semibold">Also checked, from your feedback: </span>
          {applied.sources.join(" · ")}
        </p>
      )}
      <ul className="divide-y rounded-2xl border">
        {(compliance?.checks ?? []).map((c) => (
          <li key={c.rule} className="flex items-start gap-3 p-3">
            <span className={cn("mt-0.5 grid size-6 shrink-0 place-items-center rounded-full", c.passed ? "bg-good-soft text-good" : "bg-critical-soft text-critical")}>
              {c.passed ? <Check className="size-3.5" /> : <X className="size-3.5" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{RULE_LABEL[c.rule] ?? c.rule}</p>
              <p className="text-sm text-muted-foreground">{c.detail}</p>
            </div>
            {c.citation && (
              <button onClick={() => onOpenChunk(c.citation!)} className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent hover:underline">
                <FileText className="size-3.5" /> Where it says so
              </button>
            )}
          </li>
        ))}
      </ul>
      {risk && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Volatility", pct(risk.volatility)],
            ["Beta vs market", risk.beta.toFixed(2)],
            ["Worst day (95%)", pct(risk.var95_1d)],
            ["Biggest past drop", pct(risk.max_drawdown)],
          ].map(([k, v]) => (
            <div key={k} className="rounded-2xl bg-panel-2 p-3">
              <p className="text-xs text-muted-foreground">{k}</p>
              <p className="tabular mt-0.5 font-semibold">{v}</p>
            </div>
          ))}
        </div>
      )}
      {risk?.warnings.length ? (
        <ul className="mt-3 text-sm text-warning">
          {risk.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      ) : null}
    </RunSection>
  );
}
