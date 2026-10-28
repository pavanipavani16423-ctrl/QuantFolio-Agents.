"use client";

import { useEffect, useState } from "react";
import { BookOpen, Brain, History, Link2, ShieldCheck, ShieldX } from "lucide-react";
import { Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { AuditEntry, Memory, Preference, Run } from "@/lib/types";
import { RunSection } from "./section";

export function prefText(p: Preference): string {
  if (p.kind === "exclude_ticker") return `avoid ${p.value}`;
  if (p.kind === "max_weight") return `at most ${Math.round(Number(p.value) * 100)}% per stock`;
  if (p.kind === "lower_risk") return "lower risk";
  return `“${p.value}”`;
}

const OUTCOME: Record<string, string> = { approved: "Approved", rejected: "Rejected", changed: "Changed" };

/** What the team remembered at the start of this run, by memory layer. */
export function MemorySection({ run }: { run: Run }) {
  const memory: Memory | undefined = run.result.memory;
  const research = run.result.research;
  if (!memory) return null;
  const total = memory.episodic.length + memory.semantic.length + memory.procedural.length;
  const layers = [
    {
      icon: History,
      title: "Past reviews",
      explain: "What happened the last times (episodic memory)",
      items: memory.episodic.map((e) => `${e.when} · ${OUTCOME[e.outcome] ?? e.outcome}: ${e.summary}`),
    },
    {
      icon: Brain,
      title: "Client preferences",
      explain: "Learned from your changes; they only make rules stricter (semantic memory)",
      items: memory.semantic.map(prefText),
    },
    {
      icon: BookOpen,
      title: "How to write for this client",
      explain: "Your notes, reused as guidance for the memo (procedural memory)",
      items: memory.procedural.map((p) => `“${p.value}”`),
    },
  ];
  return (
    <RunSection
      eyebrow="Memory"
      title={total ? `The team remembered ${total} thing${total > 1 ? "s" : ""} about this client.` : "Nothing remembered yet."}
      lead="Memory is written only from your decisions and checked before it is reused. Within the run, the working memory is the saved state of every step."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {layers.map(({ icon: Icon, title, explain, items }) => (
          <div key={title} className="rounded-2xl bg-panel-2 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <Icon className="size-4 text-accent" /> {title}
            </p>
            <p className="mb-2 text-xs text-muted-foreground">{explain}</p>
            {items.length ? (
              <ul className="flex flex-col gap-1.5 text-sm">
                {items.map((t) => (
                  <li key={t} className="[overflow-wrap:anywhere]">
                    {t}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-subtle-foreground">None yet.</p>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {research?.cache ? (
          <Badge tone="accent">
            Research answer reused from memory · asked {research.cache.when} · similarity {research.cache.similarity.toFixed(2)}
          </Badge>
        ) : (
          <Badge>Research answer is new (not in the research memory)</Badge>
        )}
        {memory.quarantined.length > 0 && (
          <Badge tone="warning">{memory.quarantined.length} stored note(s) not reused: they read like instructions</Badge>
        )}
      </div>
    </RunSection>
  );
}

const ACTION: Record<string, string> = {
  run_started: "Request received",
  request_blocked: "Stopped by the safety check",
  change_requested: "Change requested",
  approved: "Approved",
  rejected: "Rejected",
  orders_executed: "Practice orders placed",
  memory_forgotten: "Memory forgotten",
};

/** The run's entries in the tamper-evident audit log. */
export function AuditSection({ run }: { run: Run }) {
  const [data, setData] = useState<{ entries: AuditEntry[]; chain: { valid: boolean; entries: number } } | null>(null);
  const key = `${run.status}:${run.result.revision ?? 0}`;
  useEffect(() => {
    let live = true;
    api.audit(run.id).then((d) => live && setData(d)).catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [run.id, key]);
  if (!data) return null;
  return (
    <RunSection
      eyebrow="Audit trail"
      title="Who decided what, and when."
      lead="Every entry is chained to the one before it with a hash, so changing or deleting a past entry is detected."
      right={
        data.chain.valid ? (
          <Badge tone="good">
            <ShieldCheck className="size-3" /> Chain intact · {data.chain.entries} entries
          </Badge>
        ) : (
          <Badge tone="critical">
            <ShieldX className="size-3" /> Chain broken
          </Badge>
        )
      }
    >
      <ol className="flex flex-col gap-2">
        {data.entries.map((e) => (
          <li key={e.seq} className="grid grid-cols-[auto_1fr] gap-x-3 rounded-2xl bg-panel-2 px-4 py-3 text-sm">
            <Link2 className="mt-0.5 size-4 text-subtle-foreground" />
            <div className="min-w-0">
              <p className="font-medium">
                {ACTION[e.action] ?? e.action} <span className="font-normal text-muted-foreground">· {e.actor}</span>
              </p>
              <p className="text-xs text-subtle-foreground">
                {new Date(e.at).toLocaleString()} · <span className="font-mono">{e.hash.slice(0, 12)}…</span>
              </p>
            </div>
          </li>
        ))}
      </ol>
    </RunSection>
  );
}
