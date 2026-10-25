"use client";

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Check, Loader2, X } from "lucide-react";
import { Badge, Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import type { Run } from "@/lib/types";
import { RunSection } from "./section";

export function Recommendation({ run, onCite }: { run: Run; onCite: (n: number) => void }) {
  const memo = run.result.memo;
  const opt = run.result.optimization;
  if (!memo || !opt) return null;
  const rec = opt.proposals[opt.recommended];
  return (
    <RunSection
      id="answer"
      eyebrow="The answer"
      title={memo.headline}
      right={
        <Badge tone={memo.method === "llm" ? "accent" : "neutral"}>
          {memo.method === "llm" ? "Written by the AI model" : "Written from a template (offline mode)"}
        </Badge>
      }
    >
      <p className="text-base leading-relaxed text-muted-foreground">{memo.summary}</p>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl bg-panel-2 p-4">
          <p className="text-xs text-muted-foreground">Expected yearly return</p>
          <p className="tabular mt-1 text-2xl font-semibold">{pct(rec.expected_return)}</p>
        </div>
        <div className="rounded-2xl bg-panel-2 p-4">
          <p className="text-xs text-muted-foreground">Expected ups and downs (volatility)</p>
          <p className="tabular mt-1 text-2xl font-semibold">{pct(rec.volatility)}</p>
        </div>
        <div className="rounded-2xl bg-panel-2 p-4">
          <p className="text-xs text-muted-foreground">Stocks held</p>
          <p className="tabular mt-1 text-2xl font-semibold">{rec.selected.length}</p>
        </div>
      </div>
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Main changes</h3>
          <ul className="flex flex-col gap-1.5 text-sm">
            {memo.key_changes.map((c) => {
              const buy = c.toLowerCase().startsWith("buy");
              return (
                <li key={c} className="flex items-start gap-2">
                  {buy ? (
                    <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-good" />
                  ) : (
                    <ArrowDownRight className="mt-0.5 size-4 shrink-0 text-critical" />
                  )}
                  <span>{c}</span>
                </li>
              );
            })}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Risks to know</h3>
          <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
            {memo.risks.map((r) => (
              <li key={r} className="leading-relaxed">
                <Cited text={r} onCite={onCite} />
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-5 rounded-2xl bg-accent-soft p-4 text-sm">
        <span className="font-semibold text-accent">Quantum note · </span>
        {memo.quantum_note}
      </p>
    </RunSection>
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

export function Approval({ run, onDecided }: { run: Run; onDecided: () => void }) {
  const trades = run.result.trades;
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!trades) return null;
  const awaiting = run.status === "awaiting_approval";
  const execution = run.result.execution;
  const approval = run.result.approval;

  async function decide(approved: boolean) {
    setBusy(approved ? "approve" : "reject");
    setError(null);
    try {
      await api.decide(run.id, { approved, reviewer: reviewer.trim() || "advisor", note: note.trim() || undefined });
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the decision");
    } finally {
      setBusy(null);
    }
  }

  const buys = trades.trades.filter((t) => t.side === "buy");
  const sells = trades.trades.filter((t) => t.side === "sell");

  return (
    <RunSection
      id="approve"
      eyebrow="Your decision"
      title={
        execution
          ? "Approved. The practice trades were placed."
          : approval && !approval.approved
            ? "Rejected. No trades were placed."
            : "Approve the trades?"
      }
      lead={
        awaiting
          ? "Nothing is traded until a person approves. This is a paper (practice) account: no real money moves."
          : approval
            ? `Decision by ${approval.reviewer}${approval.note ? `: “${approval.note}”` : ""}`
            : undefined
      }
      className={cn(awaiting && "border-accent shadow-[0_0_0_4px_var(--accent-soft)]")}
    >
      <div className="grid gap-4 md:grid-cols-2">
        {[
          { label: `Sell (${sells.length})`, rows: sells, tone: "text-critical" },
          { label: `Buy (${buys.length})`, rows: buys, tone: "text-good" },
        ].map((g) => (
          <div key={g.label} className="rounded-2xl bg-panel-2 p-4">
            <h3 className={cn("mb-2 text-sm font-semibold", g.tone)}>{g.label}</h3>
            <table className="w-full text-sm">
              <tbody>
                {g.rows.map((t) => (
                  <tr key={t.ticker} className="border-b border-border last:border-0">
                    <td className="py-1.5 font-medium">{t.ticker}</td>
                    <td className="tabular py-1.5 text-muted-foreground">{t.shares.toLocaleString()} shares</td>
                    <td className="tabular py-1.5 text-right text-muted-foreground">
                      {pct(t.weight_before)} → {pct(t.weight_after)}
                    </td>
                  </tr>
                ))}
                {!g.rows.length && (
                  <tr>
                    <td className="py-1.5 text-muted-foreground">Nothing</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-subtle-foreground">
        Prices of {trades.price_date} · account value {money(trades.account_value)} · {pct(trades.turnover, 0)} of the
        account changes hands
      </p>
      {awaiting && (
        <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Your name</span>
            <input
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="e.g. Priya (advisor)"
              className="h-11 rounded-full border bg-panel-2 px-4 outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          <label className="flex flex-[1.4] flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Note (optional)</span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why you approve or reject"
              className="h-11 rounded-full border bg-panel-2 px-4 outline-none focus:ring-2 focus:ring-accent"
            />
          </label>
          <div className="flex gap-2">
            <Button variant="outline" size="lg" onClick={() => decide(false)} disabled={busy !== null}>
              {busy === "reject" ? <Loader2 className="size-4 animate-spin" /> : <X className="size-4" />} Reject
            </Button>
            <Button size="lg" onClick={() => decide(true)} disabled={busy !== null}>
              {busy === "approve" ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />} Approve
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-3 rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
      {execution && (
        <p className="mt-4 rounded-2xl bg-good-soft p-4 text-sm text-good">
          {execution.fills.length} orders filled. New account value {money(execution.account.market_value)}, cash left{" "}
          {money(execution.account.cash)}.
        </p>
      )}
    </RunSection>
  );
}
