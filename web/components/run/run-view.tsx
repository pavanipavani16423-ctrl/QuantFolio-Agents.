"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, ExternalLink, Loader2 } from "lucide-react";
import { Badge, buttonClass, EmptyState, Panel } from "@/components/ui";
import { STATUS } from "@/lib/plain";
import type { Source } from "@/lib/types";
import { BacktestChart } from "./charts";
import { Comparison, Weights } from "./compare";
import { QualitySection } from "./quality";
import { Approval, Recommendation } from "./recommendation";
import { ResearchSection, RulesSection, SourceDrawer } from "./research";
import { StepsRail } from "./steps-rail";
import { TechnicalDetails } from "./technical";
import { useRun } from "./use-run";

export function RunView({ id }: { id: string }) {
  const { run, error, refetch } = useRun(id);
  const [open, setOpen] = useState<Source | { chunk_id: string } | null>(null);

  if (error && !run) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-24">
        <EmptyState>Could not load this run: {error}</EmptyState>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="grid place-items-center py-32 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  const status = STATUS[run.status] ?? { label: run.status, tone: "neutral" as const };
  const working = run.status === "running" || run.status === "queued";
  const current = Object.values(run.steps).find((s) => s.status === "running");
  const done = Object.values(run.steps).filter((s) => s.status === "done").length;
  const total = Object.keys(run.steps).length;
  const cite = (n: number) => {
    const s = run.result.research?.sources.find((x) => x.n === n);
    if (s) setOpen(s);
  };

  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-7xl px-4 pt-8 pb-24 sm:px-6">
        <Link href="/" className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> New request
        </Link>

        {/* header */}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={status.tone}>
                {working && <span className="size-1.5 rounded-full bg-current pulse-dot" />}
                {status.label}
              </Badge>
              <span className="text-sm text-muted-foreground">
                {run.client_name} · {run.profile}
              </span>
            </div>
            <h1 className="display mt-3 max-w-4xl text-3xl font-semibold sm:text-4xl">“{run.request}”</h1>
          </div>
          {run.trace_url && (
            <a href={run.trace_url} target="_blank" rel="noreferrer" className={buttonClass("outline")}>
              See every step in Langfuse <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>

        <Panel className="mt-8 grid gap-4 lg:grid-cols-[300px_1fr]">
          {/* live steps */}
          <aside className="lg:sticky lg:top-20 lg:self-start">
            <div className="mb-3 flex items-center justify-between px-3">
              <h2 className="text-sm font-semibold">What the agents did</h2>
              <span className="tabular text-xs text-muted-foreground">
                {done}/{total}
              </span>
            </div>
            <div className="mx-3 mb-3 h-1.5 overflow-hidden rounded-full bg-card">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${(done / total) * 100}%` }} />
            </div>
            <StepsRail run={run} />
          </aside>

          {/* results */}
          <div className="flex min-w-0 flex-col gap-4">
            {working && (
              <div className="flex items-center gap-3 rounded-3xl border bg-card p-5">
                <Loader2 className="size-5 shrink-0 animate-spin text-accent" />
                <div>
                  <p className="font-semibold">{current ? current.title : "Starting the agents"}…</p>
                  <p className="text-sm text-muted-foreground">
                    Results appear below as each agent finishes. The quantum step takes the longest (about 10–20 seconds).
                  </p>
                </div>
              </div>
            )}
            {run.status === "failed" && (
              <div className="rounded-3xl border border-critical bg-critical-soft p-5 text-sm text-critical">
                The run stopped: {run.error}
              </div>
            )}
            {run.status === "blocked" && (
              <div className="rounded-3xl border border-critical bg-critical-soft p-5 text-sm text-critical">
                The portfolio broke a client rule even after the optimizer tried again, so no trades were proposed. See
                “Client rules” below.
              </div>
            )}
            <Approval run={run} onDecided={refetch} />
            <Recommendation run={run} onCite={cite} />
            <Comparison run={run} />
            <Weights run={run} />
            <BacktestChart run={run} />
            <ResearchSection run={run} onCite={cite} />
            <RulesSection run={run} onOpenChunk={(chunk_id) => setOpen({ chunk_id })} />
            <QualitySection run={run} />
            <TechnicalDetails run={run} />
          </div>
        </Panel>
      </div>
      <SourceDrawer source={open} onClose={() => setOpen(null)} />
    </div>
  );
}
