"use client";

import { CheckCircle2, CircleAlert, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { Badge, cn } from "@/components/ui";
import { CHECK_LABEL, LAYER_LABEL } from "@/lib/plain";
import type { Guardrail, Run, Verdict } from "@/lib/types";
import { RunSection } from "./section";

const LAYERS = ["input", "retrieval", "memory", "output", "action"] as const;

const VERDICT: Record<Verdict, { icon: typeof CheckCircle2; className: string; label: string }> = {
  pass: { icon: CheckCircle2, className: "text-good", label: "Passed" },
  fixed: { icon: Wrench, className: "text-accent", label: "Fixed" },
  warn: { icon: CircleAlert, className: "text-warning", label: "Note" },
  block: { icon: ShieldX, className: "text-critical", label: "Stopped" },
};

/** The latest finding per check: a re-plan after "Change" replaces the earlier proposal's checks. */
export function currentFindings(run: Run): Guardrail[] {
  const revision = run.result.revision ?? 0;
  const latest = new Map<string, Guardrail>();
  for (const g of run.guardrails ?? []) {
    const proposalStep = ["optimize", "report", "trades", "approval"].includes(g.step ?? "");
    if (proposalStep && (g.revision ?? 0) !== revision && g.step !== "approval") continue;
    latest.set(`${g.step}:${g.check}`, g);
  }
  return [...latest.values()];
}

export function SafetySummary({ run }: { run: Run }) {
  const findings = currentFindings(run);
  if (!findings.length) return null;
  const stopped = findings.filter((f) => f.verdict === "block").length;
  const fixed = findings.filter((f) => f.verdict === "fixed").length;
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      {stopped ? <ShieldX className="size-4 text-critical" /> : <ShieldCheck className="size-4 text-good" />}
      {stopped
        ? `${stopped} safety check${stopped > 1 ? "s" : ""} stopped this.`
        : `${findings.length} safety checks passed${fixed ? `, ${fixed} fixed automatically` : ""}.`}
    </p>
  );
}

export function SafetySection({ run }: { run: Run }) {
  const findings = currentFindings(run);
  if (!findings.length) return null;
  const fixed = findings.filter((f) => f.verdict === "fixed").length;
  const stopped = findings.filter((f) => f.verdict === "block").length;
  return (
    <RunSection
      eyebrow="Safety"
      title={stopped ? "A safety check stopped this." : "Every safety check passed."}
      lead="Rules, not AI, check each place where text comes in or goes out. They cannot be talked out of their decision."
      right={
        <div className="flex gap-2">
          <Badge tone="good">{findings.length - fixed - stopped} passed</Badge>
          {fixed > 0 && <Badge tone="accent">{fixed} fixed</Badge>}
          {stopped > 0 && <Badge tone="critical">{stopped} stopped</Badge>}
        </div>
      }
    >
      <div className="grid items-start gap-3 sm:grid-cols-2">
        {LAYERS.map((layer) => {
          const items = findings.filter((f) => f.layer === layer);
          if (!items.length) return null;
          return (
            <div key={layer} className="rounded-2xl bg-panel-2 p-4">
              <p className="text-sm font-semibold">{LAYER_LABEL[layer].title}</p>
              <p className="mb-3 text-xs text-muted-foreground">{LAYER_LABEL[layer].explain}</p>
              <ul className="flex flex-col gap-2">
                {items.map((f) => {
                  const v = VERDICT[f.verdict];
                  const Icon = v.icon;
                  return (
                    <li key={`${f.step}:${f.check}`} className="flex items-start gap-2 text-sm">
                      <Icon className={cn("mt-0.5 size-4 shrink-0", v.className)} aria-label={v.label} />
                      <span className="min-w-0">
                        <span className="block font-medium">{CHECK_LABEL[f.check] ?? f.check.replaceAll("_", " ")}</span>
                        <span className="block text-xs text-muted-foreground [overflow-wrap:anywhere]">{f.detail}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </RunSection>
  );
}
