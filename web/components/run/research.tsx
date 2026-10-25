"use client";

import { useEffect, useState } from "react";
import { Check, ExternalLink, FileText, X } from "lucide-react";
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

export function ResearchSection({ run, onCite }: { run: Run; onCite: (n: number) => void }) {
  const r = run.result.research;
  if (!r) return null;
  return (
    <RunSection
      id="research"
      eyebrow="Research"
      title={r.question}
      lead={`Answered only from the companies' own documents: ${run.research_sources ?? "annual reports"}. Click a number to read the exact passage.`}
      right={<Badge tone={r.method === "llm" ? "accent" : "neutral"}>{r.method === "llm" ? "AI answer" : "Quotes picked by rules (offline mode)"}</Badge>}
    >
      <p className="text-base leading-relaxed [overflow-wrap:anywhere]">
        <Cited text={r.answer} onCite={onCite} />
      </p>
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
