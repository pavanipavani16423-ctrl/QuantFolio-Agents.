"use client";

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Brain, Check, Loader2, PencilLine, X } from "lucide-react";
import { Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import type { Run } from "@/lib/types";
import { WhyThisPlan, sellReason } from "./why";

type Mode = "idle" | "change" | "reject";

/** The advisor's decision: approve, change (re-plan and learn) or reject (and say why). */
export function Decision({ run, onDecided }: { run: Run; onDecided: () => void }) {
  const r = run.result;
  const trades = r.trades;
  const opt = r.optimization;
  const [mode, setMode] = useState<Mode>("idle");
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [remove, setRemove] = useState<string[]>([]);
  const [cap, setCap] = useState<number | null>(null);
  const [lowerRisk, setLowerRisk] = useState(false);
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!trades || !opt) return null;
  const awaiting = run.status === "awaiting_approval";
  const selected = opt.proposals[opt.recommended].selected;
  const maxWeight = (r.effective_rules ?? r.rules)?.max_weight ?? 0.2;
  const minCap = 1 / selected.length;
  const capOptions = [0.1, 0.12, 0.15, 0.18].filter((c) => c < maxWeight - 1e-6 && c >= minCap - 1e-6);
  const sells = trades.trades.filter((t) => t.side === "sell");
  const buys = trades.trades.filter((t) => t.side === "buy");
  const hasChange = remove.length > 0 || cap !== null || lowerRisk;

  async function send(action: "approve" | "reject" | "change") {
    setBusy(true);
    setError(null);
    try {
      await api.decide(run.id, {
        action,
        reviewer: reviewer.trim() || "advisor",
        note: note.trim() || undefined,
        remember,
        changes: action === "change" ? { remove_tickers: remove, max_weight: cap, lower_risk: lowerRisk } : undefined,
      });
      setMode("idle");
      setRemove([]);
      setCap(null);
      setLowerRisk(false);
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send your decision");
    } finally {
      setBusy(false);
    }
  }

  // ---- finished --------------------------------------------------------------------------
  if (!awaiting) {
    if (r.execution)
      return (
        <div className="rounded-3xl border border-good bg-good-soft p-5">
          <p className="font-semibold text-good">Approved. {r.execution.fills.length} practice trades were placed.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            New account value {money(r.execution.account.market_value, run.currency)} · decided by {r.approval?.reviewer}
          </p>
        </div>
      );
    if (r.approval && !r.approval.approved)
      return (
        <div className="rounded-3xl border bg-panel-2 p-5">
          <p className="font-semibold">You rejected this plan. Nothing was traded.</p>
          {r.approval.note && <p className="mt-1 text-sm text-muted-foreground">Reason: “{r.approval.note}” (remembered for next time)</p>}
        </div>
      );
    return null;
  }

  // ---- waiting for the advisor -----------------------------------------------------------
  return (
    <section className="rounded-3xl border-2 border-accent bg-card p-5 shadow-[0_0_0_6px_var(--accent-soft)] sm:p-6" aria-label="Your decision">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 className="text-xl font-semibold">Your decision</h2>
        <p className="text-xs text-muted-foreground">
          Practice account · {trades.trades.length} orders · {pct(trades.turnover, 0)} of the money moves
        </p>
      </div>

      <WhyThisPlan run={run} />

      <p className="mt-5 text-sm font-semibold">The orders, if you approve</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {[
          { label: "Sell", rows: sells, icon: ArrowDownRight, tone: "text-critical" },
          { label: "Buy", rows: buys, icon: ArrowUpRight, tone: "text-good" },
        ].map((g) => (
          <div key={g.label} className="rounded-2xl bg-panel-2 p-3">
            <p className={cn("mb-1 flex items-center gap-1 text-sm font-semibold", g.tone)}>
              <g.icon className="size-4" /> {g.label} ({g.rows.length})
            </p>
            <ul className="text-sm">
              {g.rows.slice(0, 10).map((t) => (
                <li key={t.ticker} className="flex justify-between gap-2 py-0.5">
                  <span className="min-w-0">
                    <span className="font-medium">{t.ticker}</span>
                    <span className="ml-2 text-xs text-subtle-foreground">
                      {t.side === "sell" ? sellReason(t.ticker, run, t.weight_after) : t.weight_before > 0 ? "add more" : "new"}
                    </span>
                  </span>
                  <span className="tabular text-muted-foreground">
                    {pct(t.weight_before, 0)} → {pct(t.weight_after, 0)}
                  </span>
                </li>
              ))}
              {g.rows.length > 10 && <li className="text-xs text-subtle-foreground">+ {g.rows.length - 10} more</li>}
              {!g.rows.length && <li className="text-muted-foreground">Nothing</li>}
            </ul>
          </div>
        ))}
      </div>

      {mode === "idle" && (
        <>
        <p className="mt-5 text-xs text-muted-foreground">
          Approve places these as practice trades with a signed, single-use approval. Change asks the agents to re-plan.
          Reject stops here. Nothing happens until you choose.
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <Button size="lg" onClick={() => send("approve")} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />} Approve
          </Button>
          <Button size="lg" variant="outline" onClick={() => setMode("change")} disabled={busy}>
            <PencilLine className="size-4" /> Change
          </Button>
          <Button size="lg" variant="ghost" onClick={() => setMode("reject")} disabled={busy}>
            <X className="size-4" /> Reject
          </Button>
        </div>
        </>
      )}

      {mode === "change" && (
        <div className="mt-5 rounded-2xl bg-panel-2 p-4">
          <p className="text-sm font-semibold">What should be different?</p>
          <p className="mt-3 text-xs text-muted-foreground">Remove stocks you do not want</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {selected.map((t) => {
              const on = remove.includes(t);
              return (
                <button
                  key={t}
                  onClick={() => setRemove((cur) => (on ? cur.filter((x) => x !== t) : [...cur, t]))}
                  className={cn(
                    "rounded-full border px-3 py-1 text-sm",
                    on ? "border-critical bg-critical-soft text-critical line-through" : "bg-card hover:bg-panel",
                  )}
                  aria-pressed={on}
                >
                  {t}
                </button>
              );
            })}
          </div>
          {capOptions.length > 0 && (
            <>
              <p className="mt-4 text-xs text-muted-foreground">Smaller maximum per stock (now {pct(maxWeight, 0)})</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {capOptions.map((c) => (
                  <button
                    key={c}
                    onClick={() => setCap(cap === c ? null : c)}
                    className={cn("rounded-full border px-3 py-1 text-sm", cap === c ? "bg-foreground text-background" : "bg-card hover:bg-panel")}
                    aria-pressed={cap === c}
                  >
                    {pct(c, 0)}
                  </button>
                ))}
              </div>
            </>
          )}
          <label className="mt-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={lowerRisk} onChange={(e) => setLowerRisk(e.target.checked)} className="size-4 accent-[var(--accent)]" />
            Make it less risky
          </label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why? (optional, the agents keep it in mind)"
            className="mt-4 h-11 w-full rounded-full border bg-card px-4 text-sm outline-none focus:ring-2 focus:ring-accent"
          />
          <Footer reviewer={reviewer} setReviewer={setReviewer} remember={remember} setRemember={setRemember} />
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => send("change")} disabled={busy || !hasChange}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <PencilLine className="size-4" />} Re-plan with my changes
            </Button>
            <Button variant="ghost" onClick={() => setMode("idle")} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {mode === "reject" && (
        <div className="mt-5 rounded-2xl bg-panel-2 p-4">
          <p className="text-sm font-semibold">Why are you rejecting it?</p>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. too many trades this quarter"
            className="mt-3 h-11 w-full rounded-full border bg-card px-4 text-sm outline-none focus:ring-2 focus:ring-accent"
          />
          <Footer reviewer={reviewer} setReviewer={setReviewer} remember={remember} setRemember={setRemember} />
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="dark" onClick={() => send("reject")} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <X className="size-4" />} Reject the plan
            </Button>
            <Button variant="ghost" onClick={() => setMode("idle")} disabled={busy}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-3 rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
    </section>
  );
}

function Footer({
  reviewer,
  setReviewer,
  remember,
  setRemember,
}: {
  reviewer: string;
  setReviewer: (v: string) => void;
  remember: boolean;
  setRemember: (v: boolean) => void;
}) {
  return (
    <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
      <input
        value={reviewer}
        onChange={(e) => setReviewer(e.target.value)}
        placeholder="Your name"
        className="h-11 rounded-full border bg-card px-4 text-sm outline-none focus:ring-2 focus:ring-accent sm:w-56"
      />
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="size-4 accent-[var(--accent)]" />
        <Brain className="size-4 text-accent" /> Remember this for this client&apos;s next plans
      </label>
    </div>
  );
}
