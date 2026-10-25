"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { pct, num } from "@/lib/format";
import { METHOD } from "@/lib/plain";
import type { Run } from "@/lib/types";
import { RunSection } from "./section";

const SHOWN = ["recommended", "current", "SPY", "equal_weight"];
const axis = { stroke: "var(--subtle-foreground)", fontSize: 11, tickLine: false, axisLine: false } as const;

export function BacktestChart({ run }: { run: Run }) {
  const bt = run.result.backtest;
  if (!bt) return null;
  const keys = SHOWN.filter((k) => bt.curves[k]);
  const data = bt.dates.map((d, i) => {
    const row: Record<string, number | string> = { date: d };
    keys.forEach((k) => (row[k] = bt.curves[k][i]));
    return row;
  });
  const rec = bt.metrics.recommended;
  const spy = bt.metrics.SPY;
  const cur = bt.metrics.current;
  return (
    <RunSection
      id="backtest"
      eyebrow="Reality check"
      title="How it would have done in the last months"
      lead={`The agents only saw prices up to ${run.result.risk_profile?.window.end ?? "the cut-off"}. These ${bt.days} trading days (${bt.start} to ${bt.end}) were hidden from them, so this is a fair test. $100 invested at the start:`}
    >
      <div className="h-72 w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" {...axis} minTickGap={48} tickFormatter={(d: string) => d.slice(5)} />
            <YAxis {...axis} domain={["auto", "auto"]} width={48} />
            <Tooltip
              contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }}
              formatter={(v, name) => [`$${num(Number(v), 1)}`, METHOD[String(name)]?.short ?? String(name)]}
            />
            {keys.map((k) => (
              <Line
                key={k}
                type="monotone"
                dataKey={k}
                stroke={METHOD[k]?.color}
                strokeWidth={k === "recommended" ? 2.5 : 1.5}
                strokeDasharray={k === "SPY" ? "4 3" : undefined}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
        {keys.map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded" style={{ background: METHOD[k]?.color }} />
            {METHOD[k]?.name ?? k}: <span className="tabular font-semibold text-foreground">{pct(bt.metrics[k].total_return)}</span>
          </span>
        ))}
      </div>
      <p className="mt-4 rounded-2xl bg-panel-2 p-4 text-sm text-muted-foreground">
        {rec.total_return >= spy.total_return
          ? `The recommended portfolio beat the S&P 500 in this period (${pct(rec.total_return)} vs ${pct(spy.total_return)}).`
          : `The recommended portfolio did worse than the S&P 500 in this period (${pct(rec.total_return)} vs ${pct(spy.total_return)}). A lower-risk portfolio often lags in a rising market; a few months prove little either way.`}{" "}
        The client&apos;s current portfolio returned {pct(cur.total_return)}.
      </p>
    </RunSection>
  );
}

export function ConvergenceChart({ values }: { values: number[] }) {
  const data = values.map((v, i) => ({ step: i + 1, value: v }));
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="step" {...axis} />
          <YAxis {...axis} width={56} tickFormatter={(v: number) => v.toFixed(3)} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 12, fontSize: 12 }}
            formatter={(v) => [Number(v).toFixed(5), "energy (lower is better)"]}
            labelFormatter={(l) => `optimizer step ${l}`}
          />
          <Line type="monotone" dataKey="value" stroke="var(--series-quantum)" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
