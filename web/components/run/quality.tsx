import { ExternalLink } from "lucide-react";
import { Badge, buttonClass, cn } from "@/components/ui";
import { num, pct, signedPct } from "@/lib/format";
import { SCORE_GROUPS, SCORE_LABEL } from "@/lib/plain";
import type { Run, Score } from "@/lib/types";
import { RunSection } from "./section";

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

export function QualitySection({ run }: { run: Run }) {
  const ev = run.result.evaluation;
  if (!ev) return null;
  return (
    <RunSection
      id="quality"
      eyebrow="Quality scores"
      title="How good was this answer?"
      lead="Measured automatically after every run and sent to the Langfuse dashboard, so quality can be tracked over time."
      right={
        run.trace_url ? (
          <a href={run.trace_url} target="_blank" rel="noreferrer" className={buttonClass("outline")}>
            Open in Langfuse <ExternalLink className="size-3.5" />
          </a>
        ) : null
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        {SCORE_GROUPS.map((g) => {
          const items = g.names.filter((n) => ev.scores[n]);
          const isRagas = g.names[0] === "rag_faithfulness" || g.names[0] === "output_memo_quality";
          return (
            <div key={g.title} className="rounded-2xl bg-panel-2 p-4">
              <div className="mb-3 flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold">{g.title}</h3>
                <span className="text-xs text-subtle-foreground">{g.plain}</span>
              </div>
              {items.length ? (
                <ul className="flex flex-col gap-3">
                  {items.map((n) => {
                    const s = ev.scores[n];
                    const t = tone(n, s);
                    const kind = SCORE_LABEL[n]?.kind;
                    return (
                      <li key={n}>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span>
                            {SCORE_LABEL[n]?.name ?? n}
                            <span className="block text-xs text-muted-foreground">{SCORE_LABEL[n]?.explain}</span>
                          </span>
                          <Badge tone={t} className="tabular shrink-0 text-sm">
                            {display(n, s)}
                          </Badge>
                        </div>
                        {kind === "unit" && (
                          <div className="mt-1.5 h-1.5 rounded-full bg-card">
                            <div
                              className={cn("h-full rounded-full", t === "good" ? "bg-good" : t === "warning" ? "bg-warning" : "bg-critical")}
                              style={{ width: `${Math.max(2, Math.min(100, s.value * 100))}%` }}
                            />
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {isRagas
                    ? "Not scored: the RAGAS judge needs an AI model. Add a free Groq API key to the backend's .env file to turn it on."
                    : "No scores in this group."}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-xs text-subtle-foreground">
        Judge: {ev.judge ?? "none (offline mode)"} · RAGAS 0.4 metrics: faithfulness, answer relevancy, context precision,
        context relevance, rubric score.
      </p>
    </RunSection>
  );
}
