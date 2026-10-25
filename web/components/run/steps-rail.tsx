import { Check, CircleDashed, Loader2, X } from "lucide-react";
import { cn } from "@/components/ui";
import { seconds } from "@/lib/format";
import type { Run, Step } from "@/lib/types";

const ORDER = ["intake", "research", "risk", "mandate", "optimize", "backtest", "check", "report", "evaluate", "trades", "approval", "execute"];

const WHO: Record<string, string> = {
  intake: "Intake agent",
  research: "Research agent",
  risk: "Risk agent · A2A",
  mandate: "Compliance agent · A2A",
  optimize: "Optimizer agent",
  backtest: "Optimizer agent",
  check: "Compliance + risk · A2A",
  report: "Report writer",
  evaluate: "Quality judge",
  trades: "Trader agent",
  approval: "You",
  execute: "Trader agent",
};

function Icon({ status }: { status: Step["status"] }) {
  if (status === "done") return <Check className="size-3.5" />;
  if (status === "running") return <Loader2 className="size-3.5 animate-spin" />;
  if (status === "failed") return <X className="size-3.5" />;
  return <CircleDashed className="size-3.5" />;
}

export function StepsRail({ run }: { run: Run }) {
  const steps = ORDER.map((k) => run.steps[k]).filter(Boolean);
  const awaiting = run.status === "awaiting_approval";
  return (
    <ol className="flex flex-col gap-1" aria-label="What the agents are doing">
      {steps.map((s) => {
        const status = s.key === "approval" && awaiting ? "running" : s.status;
        return (
          <li
            key={s.key}
            className={cn(
              "flex gap-3 rounded-2xl px-3 py-2.5",
              status === "running" && "bg-card shadow-sm",
            )}
          >
            <span
              className={cn(
                "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full",
                status === "done" && "bg-good-soft text-good",
                status === "running" && "bg-accent-soft text-accent",
                status === "failed" && "bg-critical-soft text-critical",
                status === "pending" && "text-subtle-foreground",
              )}
            >
              <Icon status={status} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className={cn("text-sm", status === "pending" ? "text-subtle-foreground" : "font-medium")}>
                  {s.title}
                </span>
                {s.seconds !== undefined && status === "done" && (
                  <span className="tabular shrink-0 text-[11px] text-subtle-foreground">{seconds(s.seconds)}</span>
                )}
              </div>
              <p className="text-[11px] uppercase tracking-wide text-subtle-foreground">
                {WHO[s.key]}
                {s.attempt && s.attempt > 1 ? ` · try ${s.attempt}` : ""}
              </p>
              {status !== "pending" && (s.summary || s.error) && (
                <p className={cn("mt-1 line-clamp-3 text-xs", s.error ? "text-critical" : "text-muted-foreground")}>
                  {s.error ?? s.summary}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
