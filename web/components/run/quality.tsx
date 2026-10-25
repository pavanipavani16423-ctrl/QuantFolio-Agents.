import { ExternalLink, Loader2 } from "lucide-react";
import { buttonClass, cn } from "@/components/ui";
import { num, pct, signedPct } from "@/lib/format";
import { SCORE_LABEL } from "@/lib/plain";
import type { Run, Score } from "@/lib/types";
import { RunSection } from "./section";

const KEY_SCORES = [
  "rag_faithfulness",
  "rag_answer_relevancy",
  "rag_context_precision",
  "output_memo_quality",
  "output_rule_extraction_accuracy",
  "output_compliance_pass",
];

function display(name: string, s: Score) {
  const kind = SCORE_LABEL[name]?.kind ?? "unit";
  if (kind === "bool") return s.value >= 0.5 ? "Yes" : "No";
  if (kind === "gap") return pct(s.value);
  if (kind === "pct") return signedPct(s.value);
  if (kind === "raw") return num(s.value);
  return pct(s.value, 0);
}

function tone(name: string, s: Score): "good" | "warning" | "critical" | "neutral" {
  const kind = SCORE_LABEL[name]?.kind ?? "unit";
  if (kind === "bool") return s.value >= 0.5 ? "good" : "critical";
  if (kind === "gap") return s.value <= 0.001 ? "good" : s.value < 0.05 ? "warning" : "critical";
  if (kind === "unit") return s.value >= 0.8 ? "good" : s.value >= 0.5 ? "warning" : "critical";
  return "neutral";
}

const TONE = {
  good: "text-good",
  warning: "text-warning",
  critical: "text-critical",
  neutral: "text-foreground",
};

export function QualitySection({ run }: { run: Run }) {
  const ev = run.result.evaluation;
  if (!ev) return null;
  const running = ev.ragas_status === "running";
  const rest = Object.keys(ev.scores).filter((n) => !KEY_SCORES.includes(n) && SCORE_LABEL[n]);
  return (
    <RunSection
      id="quality"
      eyebrow="Quality"
      title="How good is this answer?"
      lead="Checked automatically. The first four are RAGAS scores from an AI judge; all scores are also on the Langfuse dashboard."
      right={
        run.trace_url ? (
          <a href={run.trace_url} target="_blank" rel="noreferrer" className={buttonClass("outline")}>
            Langfuse <ExternalLink className="size-3.5" />
          </a>
        ) : null
      }
    >
      {running && (
        <p className="mb-4 flex items-center gap-2 rounded-2xl bg-panel-2 p-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin text-accent" /> The AI judge is still scoring (about a minute). You can
          already decide.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {KEY_SCORES.map((n) => {
          const s = ev.scores[n];
          return (
            <div key={n} className="rounded-2xl bg-panel-2 p-3">
              <p className="text-xs text-muted-foreground">{SCORE_LABEL[n]?.name}</p>
              <p className={cn("tabular mt-1 text-2xl font-semibold", s ? TONE[tone(n, s)] : "text-subtle-foreground")}>
                {s ? display(n, s) : running ? "…" : "–"}
              </p>
              <p className="mt-0.5 text-[11px] leading-snug text-subtle-foreground">{SCORE_LABEL[n]?.explain}</p>
            </div>
          );
        })}
      </div>
      {rest.length > 0 && (
        <details className="mt-4 rounded-2xl border p-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground">More scores ({rest.length})</summary>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {rest.map((n) => (
              <li key={n} className="flex items-center justify-between gap-3">
                <span>
                  {SCORE_LABEL[n]?.name}
                  <span className="block text-xs text-subtle-foreground">{SCORE_LABEL[n]?.explain}</span>
                </span>
                <span className={cn("tabular font-semibold", TONE[tone(n, ev.scores[n])])}>{display(n, ev.scores[n])}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!running && ev.notes.length > 0 && (
        <p className="mt-3 text-xs text-subtle-foreground">{ev.notes.join(" · ")}</p>
      )}
      <p className="mt-3 text-xs text-subtle-foreground">Judge: {ev.judge ?? (running ? "working" : "none (offline mode)")}</p>
    </RunSection>
  );
}
