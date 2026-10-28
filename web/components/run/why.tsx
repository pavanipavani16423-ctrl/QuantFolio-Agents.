"use client";

import { CheckCircle2, CircleX, Lightbulb } from "lucide-react";
import { cn } from "@/components/ui";
import { pct } from "@/lib/format";
import { riskWord } from "@/lib/plain";
import type { Run } from "@/lib/types";


/** Reasons for one chosen stock, from the numbers the optimizer actually used. */
function reasons(t: string, run: Run, chosen: string[]): string[] {
  const r = run.result;
  const rp = r.risk_profile;
  const pool = r.optimization?.problem.tickers ?? [];
  if (!rp) return [];
  const out: string[] = [];
  const rank = (values: Record<string, number>, desc: boolean) =>
    [...pool].sort((a, b) => (desc ? values[b] - values[a] : values[a] - values[b])).indexOf(t);
  const third = Math.max(1, Math.round(pool.length / 3));
  if (r.intake?.focus_tickers.includes(t)) out.push("you asked about it");
  if (rank(rp.expected_return, true) < third) out.push(`strong expected return (${pct(rp.expected_return[t], 0)} a year)`);
  if (rank(rp.volatility, false) < third) out.push(`steadier than most (ups and downs ${pct(rp.volatility[t], 0)})`);
  const sector = rp.sectors[t];
  if (sector && chosen.filter((x) => rp.sectors[x] === sector).length === 1) out.push(`the only ${sector} stock: spreads the risk`);
  if (!out.length) out.push("improves the balance of return and risk");
  return out.slice(0, 3);
}

/** Why the plan looks like this: the request, the client's rules, and the reason for each stock. */
export function WhyThisPlan({ run }: { run: Run }) {
  const r = run.result;
  const opt = r.optimization;
  const rules = r.effective_rules ?? r.rules;
  if (!opt || !rules) return null;
  const best = opt.proposals[opt.recommended];
  const chosen = [...best.selected].sort((a, b) => (best.weights[b] ?? 0) - (best.weights[a] ?? 0));
  const rp = r.risk_profile;
  const allowed = new Set(opt.problem.tickers);
  const leftOut = (rp?.tickers ?? []).filter((t) => !allowed.has(t));
  const removed = new Set(r.applied?.removed ?? []);
  const byRules = leftOut.filter((t) => !removed.has(t));
  const checks = r.compliance?.checks ?? [];
  const passed = checks.filter((c) => c.passed).length;
  const flags = r.research?.risk_flags ?? [];
  const combos = opt.combinations ?? opt.search.subsets_evaluated;
  const askedLeftOut = (r.intake?.focus_tickers ?? []).filter((t) => !chosen.includes(t));

  const ruleRows: { text: string; ok: boolean }[] = [
    { text: `Exactly ${rules.holdings} stocks`, ok: chosen.length === rules.holdings },
    { text: `No stock above ${pct(rules.max_weight, 0)}, none below ${pct(rules.min_weight, 0)}`, ok: best.feasible },
    { text: `No sector above ${pct(rules.max_sector_weight, 0)}`, ok: best.feasible },
    { text: `Ups and downs at most ${pct(rules.max_volatility, 0)} (this plan: ${pct(best.volatility, 0)})`, ok: best.volatility_limit_met },
  ];
  const excluded = [...rules.excluded_sectors, ...rules.excluded_tickers];
  if (excluded.length) ruleRows.push({ text: `Leaves out ${excluded.join(", ")}`, ok: true });
  if (removed.size) ruleRows.push({ text: `Your change: removed ${[...removed].join(", ")}`, ok: true });
  if (r.applied?.max_weight) ruleRows.push({ text: `Your change: at most ${pct(r.applied.max_weight, 0)} per stock`, ok: true });

  return (
    <div className="mt-4 rounded-2xl bg-panel-2 p-4">
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Lightbulb className="size-4 text-accent" /> Why this plan
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        You asked: <span className="text-foreground">“{r.intake?.research_question ?? run.request}”</span>. Following{" "}
        {run.client_name}&apos;s rules ({riskWord(rules.risk_aversion)} risk), the agents kept {opt.candidates} allowed stocks
        {combos ? `, compared ${combos.toLocaleString()} possible combinations` : ""} and chose the {chosen.length} below:
        expected {pct(best.expected_return, 1)} a year with ups and downs of {pct(best.volatility, 1)}. Check the reasons, then decide.
      </p>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
            The client&apos;s rules{checks.length ? ` · ${passed} of ${checks.length} met` : ""}
          </p>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {ruleRows.map((row) => (
              <li key={row.text} className="flex items-start gap-2">
                {row.ok ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" aria-label="met" />
                ) : (
                  <CircleX className="mt-0.5 size-4 shrink-0 text-critical" aria-label="not met" />
                )}
                <span>{row.text}</span>
              </li>
            ))}
          </ul>
          {byRules.length > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">Not allowed by the rules: {byRules.join(", ")}.</p>
          )}
          {askedLeftOut.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              You asked about {askedLeftOut.join(", ")}:{" "}
              {askedLeftOut.every((t) => !allowed.has(t))
                ? "the rules do not allow it"
                : "researched, but the best combination for these rules left it out"}
              . The Research tab has what the reports say.
            </p>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">Why these stocks</p>
          <ul className="mt-2 divide-y divide-border rounded-xl border bg-card text-sm">
            {chosen.map((t) => {
              const risks = flags.filter((f) => f.ticker === t).length;
              return (
                <li key={t} className="flex items-start gap-3 px-3 py-2">
                  <span className="w-24 shrink-0">
                    <span className="block font-semibold">{t}</span>
                    <span className="block text-xs text-subtle-foreground">{rp?.sectors[t]}</span>
                  </span>
                  <span className="min-w-0 flex-1 text-muted-foreground">
                    {reasons(t, run, chosen).join(" · ")}
                    {risks > 0 && <span className="text-warning"> · research found {risks} risk{risks > 1 ? "s" : ""} (see Research)</span>}
                  </span>
                  <span className={cn("tabular shrink-0 font-medium")}>{pct(best.weights[t], 0)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

/** Why a stock is being sold, in a few words. */
export function sellReason(t: string, run: Run, weightAfter: number): string {
  const r = run.result;
  const rules = r.effective_rules ?? r.rules;
  if (r.applied?.removed.includes(t)) return "you removed it";
  if (rules?.excluded_tickers.includes(t)) return "not allowed by the rules";
  const sector = r.risk_profile?.sectors[t];
  if (sector && rules?.excluded_sectors.includes(sector)) return `${sector} is not allowed`;
  if (weightAfter > 0) return "trimmed to the target";
  return "not in the best combination";
}
