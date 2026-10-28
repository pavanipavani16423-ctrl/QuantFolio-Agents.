import { Check, Loader2 } from "lucide-react";
import { cn } from "@/components/ui";
import { STAGES } from "@/lib/plain";
import type { Run } from "@/lib/types";

type StageState = "done" | "active" | "waiting" | "failed";

function stageState(run: Run, steps: string[]): StageState {
  const all = steps.map((k) => run.steps[k]).filter(Boolean);
  if (all.some((s) => s.status === "failed")) return "failed";
  if (steps.includes("approval") && run.status === "awaiting_approval") return "active";
  if (all.some((s) => s.status === "running")) return "active";
  const done = all.filter((s) => s.status === "done").length;
  if (done === all.length) return "done";
  if (steps.includes("approval") && ["rejected", "executed", "approved"].includes(run.status)) return "done";
  return done > 0 ? "active" : "waiting";
}

/** Five plain stages instead of twelve technical steps. */
export function Stepper({ run }: { run: Run }) {
  const states = STAGES.map((s) => stageState(run, s.steps));
  const current = Object.values(run.steps).find((s) => s.status === "running");
  const caption =
    run.status === "awaiting_approval"
      ? "Ready for your decision"
      : run.status === "executed"
        ? "Done: practice trades placed"
        : run.status === "rejected"
          ? "Done: you rejected the plan"
          : run.status === "failed"
            ? `Stopped: ${run.error ?? "an error"}`
            : run.status === "blocked"
              ? "Stopped by a safety check (see why above)"
              : current
                ? `${current.title}…`
                : "Starting…";
  return (
    <div className="rounded-3xl border bg-card p-4 sm:p-5">
      <ol className="grid grid-cols-5 gap-1 sm:gap-2" aria-label="Progress">
        {STAGES.map((stage, i) => {
          const st = states[i];
          return (
            <li key={stage.key} className="flex flex-col items-center gap-2 text-center">
              <span className="flex w-full items-center">
                <span className={cn("h-0.5 flex-1", i === 0 ? "bg-transparent" : states[i - 1] === "done" ? "bg-good" : "bg-panel")} />
                <span
                  className={cn(
                    "grid size-9 shrink-0 place-items-center rounded-full border-2 text-sm font-semibold",
                    st === "done" && "border-good bg-good text-white",
                    st === "active" && "border-accent bg-accent-soft text-accent",
                    st === "waiting" && "border-panel text-subtle-foreground",
                    st === "failed" && "border-critical bg-critical-soft text-critical",
                  )}
                >
                  {st === "done" ? <Check className="size-4" /> : st === "active" && stage.key !== "decide" ? <Loader2 className="size-4 animate-spin" /> : i + 1}
                </span>
                <span className={cn("h-0.5 flex-1", i === STAGES.length - 1 ? "bg-transparent" : st === "done" ? "bg-good" : "bg-panel")} />
              </span>
              <span className={cn("text-[11px] leading-tight sm:text-sm", st === "waiting" ? "text-subtle-foreground" : "font-medium")}>
                {stage.title}
              </span>
            </li>
          );
        })}
      </ol>
      <p className={cn("mt-4 text-center text-sm", run.status === "failed" || run.status === "blocked" ? "text-critical" : "text-muted-foreground")}>
        {caption}
      </p>
    </div>
  );
}
