"use client";

import { ArrowDownRight, ArrowUpRight, Atom, Brain } from "lucide-react";
import { pct } from "@/lib/format";
import type { Run } from "@/lib/types";

/** The memo in plain words: what we recommend, what changes, what to watch out for. */
export function Recommendation({ run, onCite }: { run: Run; onCite: (n: number) => void }) {
  const memo = run.result.memo;
  const opt = run.result.optimization;
  const applied = run.result.applied;
  if (!memo || !opt) return null;
  const rec = opt.proposals[opt.recommended];
  return (
    <section className="flex flex-col gap-5" aria-label="Recommendation">
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

      {applied && applied.sources.length > 0 && (
        <p className="flex items-start gap-2 rounded-2xl bg-accent-soft p-3 text-sm">
          <Brain className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>
            <span className="font-semibold">Following your feedback: </span>
            {applied.sources.join(" · ")}
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

      <p className="flex items-start gap-2 rounded-2xl border p-3 text-sm text-muted-foreground">
        <Atom className="mt-0.5 size-4 shrink-0 text-quantum" />
        <span>{memo.quantum_note}</span>
      </p>
    </section>
  );
}

/** Renders "[3]" markers as clickable source chips. */
export function Cited({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d+\])/g);
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
