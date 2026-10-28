"use client";

import { ArrowDownRight, ArrowUpRight, Brain, Download, Printer, Search, ShieldCheck } from "lucide-react";
import { pct } from "@/lib/format";
import { clientReportMarkdown, download } from "@/lib/report";
import type { Run } from "@/lib/types";

/** The memo in plain words: what we recommend, what changes, what to watch out for. */
export function Recommendation({ run, onCite }: { run: Run; onCite: (n: number) => void }) {
  const memo = run.result.memo;
  const opt = run.result.optimization;
  const applied = run.result.applied;
  const memory = run.result.memory;
  if (!memo || !opt) return null;
  const rec = opt.proposals[opt.recommended];
  return (
    <section className="flex flex-col gap-5" aria-label="Recommendation">
      <div className="no-print -mb-2 flex flex-wrap justify-end gap-2">
        <button
          onClick={() => download(`report-${run.client_id}-${run.id}.md`, clientReportMarkdown(run))}
          className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-panel"
        >
          <Download className="size-3.5" /> Download client report
        </button>
        <button onClick={() => window.print()} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-panel">
          <Printer className="size-3.5" /> Print / PDF
        </button>
      </div>
      <div>
        <h2 className="text-2xl font-semibold leading-snug tracking-tight">{memo.headline}</h2>
        <p className="mt-3 leading-relaxed text-muted-foreground">{memo.summary}</p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          ["Expected yearly return", pct(rec.expected_return)],
          ["Expected ups and downs", pct(rec.volatility)],
          ["Stocks", String(rec.selected.length)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-2xl bg-panel-2 p-3 sm:p-4">
            <p className="text-[11px] text-muted-foreground sm:text-xs">{k}</p>
            <p className="tabular mt-1 text-xl font-semibold sm:text-2xl">{v}</p>
          </div>
        ))}
      </div>

      {((applied && applied.sources.length > 0) || (memory?.procedural.length ?? 0) > 0) && (
        <p className="flex items-start gap-2 rounded-2xl bg-accent-soft p-3 text-sm">
          <Brain className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>
            <span className="font-semibold">Following your feedback: </span>
            {[...(applied?.sources ?? []), ...(memory?.procedural ?? []).map((p) => `“${p.value}”`)].join(" · ")}
          </span>
        </p>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">What changes</h3>
          <ul className="flex flex-col gap-1.5 text-sm">
            {memo.key_changes.map((c) => {
              const buy = /^(buy|add|increase|raise|new)\b/i.test(c.trim());
              return (
                <li key={c} className="flex items-start gap-2">
                  {buy ? <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-good" /> : <ArrowDownRight className="mt-0.5 size-4 shrink-0 text-critical" />}
                  <span>{c}</span>
                </li>
              );
            })}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Risks to know</h3>
          <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
            {memo.risks.map((r) => (
              <li key={r} className="leading-relaxed [overflow-wrap:anywhere]">
                <Cited text={r} onCite={onCite} />
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex flex-col gap-2 rounded-2xl border p-3 text-sm text-muted-foreground">
        <p className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-good" />
          <span>
            Checked before you see it: numbers match the facts, every stock is in the plan, no promises of returns
            {memo.self_corrections ? "; the first draft failed a check and was rewritten" : ""}
            {memo.method === "template_after_guardrail" ? "; the AI drafts failed the checks, so a fact-based template was used" : ""}.
          </span>
        </p>
        {opt.combinations ? (
          <p className="flex items-start gap-2">
            <Search className="mt-0.5 size-4 shrink-0 text-accent" />
            <span>
              The {rec.selected.length} stocks are the best of all {opt.combinations.toLocaleString()} possible combinations of the{" "}
              {opt.candidates} allowed stocks.
            </span>
          </p>
        ) : null}
      </div>
    </section>
  );
}

/** Renders "[3]" markers as clickable source chips. */
export function Cited({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  // "... risk [1]." -> the full stop after a final citation would wrap alone under the chip
  const parts = text.replace(/\]\.\s*$/, "]").split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        return (
          <button
            key={i}
            onClick={() => onCite(Number(m[1]))}
            className="mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-md bg-accent-soft px-1 align-text-top text-[11px] font-semibold text-accent hover:bg-accent hover:text-white"
            aria-label={`Show source ${m[1]}`}
          >
            {m[1]}
          </button>
        );
      })}
    </>
  );
}
