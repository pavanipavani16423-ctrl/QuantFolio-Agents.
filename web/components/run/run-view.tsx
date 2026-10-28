"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Loader2, ShieldX } from "lucide-react";
import { Badge, ButtonLink, cn, EmptyState } from "@/components/ui";
import { MARKET_LABEL, STATUS } from "@/lib/plain";
import type { Source } from "@/lib/types";
import { BacktestChart } from "./charts";
import { Comparison, Weights } from "./compare";
import { Decision } from "./decision";
import { AuditSection, MemorySection } from "./memory";
import { QualitySection } from "./quality";
import { Recommendation } from "./recommendation";
import { ResearchSection, RulesSection, SourceDrawer } from "./research";
import { SafetySection, SafetySummary } from "./safety";
import { RunSection } from "./section";
import { Stepper } from "./stepper";
import { StepsRail } from "./steps-rail";
import { TechnicalDetails } from "./technical";
import { useRun } from "./use-run";

const TABS = [
  { key: "plan", label: "Recommendation" },
  { key: "research", label: "Research" },
  { key: "checks", label: "Checks" },
  { key: "details", label: "Details" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function RunView({ id }: { id: string }) {
  const { run, error, refetch } = useRun(id);
  const [tab, setTab] = useState<TabKey>("plan");
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

  const status = STATUS[run.status] ?? {
    label: run.status,
    tone: "neutral" as const,
  };
  const working = run.status === "running" || run.status === "queued";
  const cite = (n: number) => {
    const s = run.result.research?.sources.find((x) => x.n === n);
    if (s) setOpen(s);
  };
  const ready = Boolean(run.result.memo);

  return (
    <div className="hero-glow">
      <div className="mx-auto max-w-4xl px-4 pt-6 pb-24 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> New request
        </Link>

        {/* header */}
        <header className="mt-5">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge tone={status.tone}>
              {working && (
                <span className="size-1.5 rounded-full bg-current pulse-dot" />
              )}
              {status.label}
            </Badge>
            <span>
              {run.client_name} · {MARKET_LABEL[run.market]?.name ?? run.market}
            </span>
          </div>
          <h1 className="mt-3 text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">
            “{run.request}”
          </h1>
          <div className="mt-2">
            <SafetySummary run={run} />
          </div>
        </header>

        {run.status === "blocked" && run.blocked_reason && (
          <Blocked reason={run.blocked_reason} early={!run.result.intake} />
        )}

        {run.result.intake && (
          <div className="no-print mt-6">
            <Stepper run={run} />
          </div>
        )}

        {/* the decision comes first when it is needed */}
        <div className="no-print mt-4">
          <Decision run={run} onDecided={refetch} />
        </div>

        {/* tabs (not for a request the safety check stopped before any agent ran) */}
        {run.result.intake && (
          <>
            <nav
              className="mt-6 flex gap-1 overflow-x-auto rounded-full border bg-card p-1"
              role="tablist"
              aria-label="Run sections"
            >
              {TABS.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "flex-1 whitespace-nowrap rounded-full px-4 py-2 text-sm",
                    tab === t.key
                      ? "bg-foreground font-semibold text-background"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </nav>

            <div className="mt-4 flex flex-col gap-4" role="tabpanel">
              {tab === "plan" &&
                (ready ? (
                  <div className="rounded-3xl border bg-card p-5 sm:p-6">
                    <Recommendation run={run} onCite={cite} />
                  </div>
                ) : (
                  <Waiting
                    text="The recommendation appears here when the agents finish (under a minute)."
                    working={working}
                  />
                ))}

              {tab === "research" &&
                (run.result.research ? (
                  <ResearchSection run={run} onCite={cite} />
                ) : (
                  <Waiting
                    text="The research answer appears here in a few seconds."
                    working={working}
                  />
                ))}

              {tab === "checks" && (
                <>
                  <SafetySection run={run} />
                  {run.result.rules ? (
                    <RulesSection
                      run={run}
                      onOpenChunk={(chunk_id) => setOpen({ chunk_id })}
                    />
                  ) : (
                    <Waiting
                      text="The client's rules appear here once they are read."
                      working={working}
                    />
                  )}
                  <QualitySection run={run} />
                </>
              )}

              {tab === "details" && (
                <>
                  <Comparison run={run} />
                  <Weights run={run} />
                  <BacktestChart run={run} />
                  <MemorySection run={run} />
                  <AuditSection run={run} />
                  <RunSection
                    eyebrow="Agents"
                    title="What each agent did"
                    lead="Every step, in order. The same steps are in the Langfuse trace."
                  >
                    <StepsRail run={run} />
                  </RunSection>
                  <TechnicalDetails run={run} />
                </>
              )}
            </div>
          </>
        )}
        {!run.result.intake && run.status === "blocked" && (
          <div className="mt-4 flex flex-col gap-4">
            <SafetySection run={run} />
            <AuditSection run={run} />
          </div>
        )}
      </div>
      <SourceDrawer source={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function Blocked({ reason, early }: { reason: string; early: boolean }) {
  return (
    <div className="mt-6 rounded-3xl border border-critical/30 bg-critical-soft/40 p-5 sm:p-6">
      <p className="flex items-center gap-2 font-semibold text-critical">
        <ShieldX className="size-5" />{" "}
        {early ? "This request was not started" : "No trades were proposed"}
      </p>
      <p className="mt-2 text-sm [overflow-wrap:anywhere]">{reason}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        {early
          ? "Nothing was sent to an AI model and nothing was traded. Rephrase the request as a question about the client's portfolio or companies."
          : "The plan was checked and stopped before it reached you. Nothing was traded."}
      </p>
      {early && (
        <ButtonLink href="/" variant="outline" className="mt-4">
          Write a new request
        </ButtonLink>
      )}
    </div>
  );
}

function Waiting({ text, working }: { text: string; working: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-3xl border bg-card p-6 text-sm text-muted-foreground">
      {working && <Loader2 className="size-4 animate-spin text-accent" />}
      {text}
    </div>
  );
}
