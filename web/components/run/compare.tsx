import { Check, Crown, Minus } from "lucide-react";
import { Badge, cn } from "@/components/ui";
import { pct, seconds } from "@/lib/format";
import { METHOD } from "@/lib/plain";
import type { Run } from "@/lib/types";
import { RunSection } from "./section";

const ORDER = ["classical", "quantum", "hybrid", "greedy"];

export function Comparison({ run }: { run: Run }) {
  const opt = run.result.optimization;
  if (!opt) return null;
  const best = opt.proposals.classical;
  const bestSet = new Set(best.selected);
  const methods = ORDER.filter((m) => opt.proposals[m]);
  return (
    <RunSection
      id="compare"
      eyebrow="Normal vs quantum"
      title={
        opt.quantum_found_optimum ? (
          <>The quantum computer found the same best portfolio.</>
        ) : opt.quantum_gap !== undefined ? (
          <>The quantum computer came within {pct(opt.quantum_gap)} of the best.</>
        ) : (
          <>The normal computer chose the stocks.</>
        )
      }
      lead={`Choosing ${opt.problem.k} of ${opt.problem.tickers.length} allowed stocks has ${opt.classical.subsets_evaluated.toLocaleString()} possible combinations. The quantum version uses one qubit per stock: ${opt.qubits} qubits.`}
    >
      <div className="grid gap-3 md:grid-cols-2">
        {methods.map((m) => {
          const p = opt.proposals[m];
          const same = p.selected.filter((t) => bestSet.has(t)).length;
          const quality = best.selection_utility > 0 ? p.selection_utility / best.selection_utility : 1;
          const isRec = opt.recommended === m;
          return (
            <div
              key={m}
              className={cn("flex flex-col gap-3 rounded-2xl border p-4", isRec ? "border-accent bg-accent-soft/40" : "bg-panel-2")}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-semibold">
                  <span className="size-2.5 rounded-full" style={{ background: METHOD[m].color }} />
                  {METHOD[m].name}
                </span>
                {isRec && (
                  <Badge tone="accent">
                    <Crown className="size-3" /> Used
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{METHOD[m].explain}</p>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <p className="text-xs text-subtle-foreground">Quality vs best</p>
                  <p className="tabular text-lg font-semibold">{pct(Math.min(quality, 1), 1)}</p>
                </div>
                <div>
                  <p className="text-xs text-subtle-foreground">Time</p>
                  <p className="tabular text-lg font-semibold">{seconds(p.seconds)}</p>
                </div>
              </div>
              <p className="flex items-center gap-1.5 text-xs">
                {same === best.selected.length ? (
                  <>
                    <Check className="size-3.5 text-good" /> Same {same} stocks as the best answer
                  </>
                ) : (
                  <>
                    <Minus className="size-3.5 text-warning" /> {same} of {best.selected.length} stocks match the best answer
                  </>
                )}
              </p>
              <div className="flex flex-wrap gap-1">
                {p.selected.map((t) => (
                  <span
                    key={t}
                    className={cn(
                      "rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                      bestSet.has(t) ? "bg-card" : "bg-warning-soft text-warning",
                    )}
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {Object.keys(opt.errors).length > 0 && (
        <ul className="mt-3 text-xs text-muted-foreground">
          {Object.entries(opt.errors).map(([k, v]) => (
            <li key={k}>
              {METHOD[k]?.name ?? k}: {v}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-subtle-foreground">
        “Quality vs best” compares how good each set of stocks is (expected return minus a risk penalty set by the
        client&apos;s rules). The quantum computer is simulated on this laptop, so its time is not what real quantum
        hardware would take.
      </p>
    </RunSection>
  );
}

export function Weights({ run }: { run: Run }) {
  const opt = run.result.optimization;
  const trades = run.result.trades;
  if (!opt) return null;
  const rec = opt.proposals[opt.recommended];
  const before: Record<string, number> = {};
  trades?.trades.forEach((t) => (before[t.ticker] = t.weight_before));
  const sectors = run.result.risk_profile?.sectors ?? {};
  const rows = Object.entries(rec.weights).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...rows.map((r) => r[1]), 0.01);
  const sectorRows = Object.entries(rec.details.sector_weights).sort((a, b) => b[1] - a[1]);
  const rules = run.result.rules;
  return (
    <RunSection
      id="portfolio"
      eyebrow="The portfolio"
      title="How the money is split"
      lead={rules ? `Rules: ${pct(rules.min_weight, 0)}–${pct(rules.max_weight, 0)} per stock, at most ${pct(rules.max_sector_weight, 0)} per industry.` : undefined}
    >
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <ul className="flex flex-col gap-2">
          {rows.map(([t, w]) => (
            <li key={t} className="grid grid-cols-[7.5rem_1fr_3.5rem] items-center gap-3 text-sm">
              <span className="min-w-0 leading-tight">
                <span className="block font-semibold">{t}</span>
                <span className="block truncate text-[11px] text-subtle-foreground">{sectors[t]}</span>
              </span>
              <div className="relative h-6 rounded-full bg-panel-2">
                <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${(w / max) * 100}%` }} />
                {before[t] !== undefined && before[t] > 0 && (
                  <div
                    className="absolute inset-y-1 w-0.5 rounded bg-foreground/50"
                    style={{ left: `${Math.min((before[t] / max) * 100, 100)}%` }}
                    title={`Before: ${pct(before[t])}`}
                  />
                )}
              </div>
              <span className="tabular text-right">{pct(w)}</span>
            </li>
          ))}
        </ul>
        <div className="rounded-2xl bg-panel-2 p-4">
          <h3 className="mb-3 text-sm font-semibold">By industry</h3>
          <ul className="flex flex-col gap-2 text-sm">
            {sectorRows.map(([s, w]) => (
              <li key={s} className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">{s}</span>
                <span className="tabular font-medium">{pct(w)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-subtle-foreground">The thin dark line on a bar marks the weight before rebalancing.</p>
        </div>
      </div>
    </RunSection>
  );
}
