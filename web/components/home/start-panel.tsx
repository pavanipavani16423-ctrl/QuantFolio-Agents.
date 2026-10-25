"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Brain, Check, ChevronDown, FileText, Loader2, X } from "lucide-react";
import { Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { MARKET_LABEL, METHOD } from "@/lib/plain";
import type { Client, Preference } from "@/lib/types";

const CLIENT_HINT: Record<string, { who: string; rules: string; examples: string[] }> = {
  "C-101": {
    who: "Retired teacher",
    rules: "Low risk · 10 stocks · max 15% each",
    examples: [
      "Rebalance Meera's portfolio. What risks could hurt the earnings of Johnson & Johnson and Coca-Cola?",
      "Rebalance the portfolio. Is Walmart's business stable?",
    ],
  },
  "C-102": {
    who: "Environmental charity",
    rules: "No oil & gas · 8 stocks · max 20% each",
    examples: [
      "Rebalance the GreenLeaf endowment. What climate or environmental risks do NVIDIA and NextEra disclose?",
      "Rebalance the endowment. What are Microsoft's main risks?",
    ],
  },
  "C-103": {
    who: "Family office",
    rules: "No Pfizer · 12 stocks · max 12% each",
    examples: [
      "Rebalance the Kumar family portfolio. What are the main risks for Apple and JPMorgan?",
      "Rebalance the portfolio. How exposed is Amazon to competition?",
    ],
  },
  "C-201": {
    who: "Family trust, Pune",
    rules: "No tobacco (ITC) · 8 stocks · max 18% each",
    examples: [
      "Rebalance the Sharma trust portfolio. What risks do Reliance and TCS report?",
      "Rebalance the portfolio. What sustainability risks do Tata Steel and NTPC disclose in their BRSR?",
    ],
  },
};

const METHODS = ["classical", "quantum", "hybrid"] as const;

function prefText(p: Preference): string {
  if (p.kind === "exclude_ticker") return `avoid ${p.value}`;
  if (p.kind === "max_weight") return `max ${Math.round(Number(p.value) * 100)}% per stock`;
  if (p.kind === "lower_risk") return "lower risk";
  return `“${p.value}”`;
}

function RulesDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    api.mandate(clientId).then((m) => setText(m.text)).catch(() => setText("Could not load the document."));
  }, [clientId]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose} role="dialog" aria-modal>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-3xl bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h3 className="text-lg font-semibold">The client&apos;s rules (example document)</h3>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-panel" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-muted-foreground">{text ?? "Loading…"}</pre>
      </div>
    </div>
  );
}

export function StartPanel() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clientId, setClientId] = useState("C-102");
  const [request, setRequest] = useState(CLIENT_HINT["C-102"].examples[0]);
  const [methods, setMethods] = useState<string[]>([...METHODS]);
  const [busy, setBusy] = useState(false);
  const [showRules, setShowRules] = useState<string | null>(null);
  const [showOptions, setShowOptions] = useState(false);
  const [prefs, setPrefs] = useState<Record<string, Preference[]>>({});

  useEffect(() => {
    api
      .clients()
      .then((cs) => {
        setClients(cs);
        cs.forEach((c) =>
          api
            .preferences(c.client_id)
            .then((p) => setPrefs((cur) => ({ ...cur, [c.client_id]: p })))
            .catch(() => undefined),
        );
      })
      .catch(() => setError("The backend is not running. Start it with: uv run uvicorn app.main:app --port 8000"));
  }, []);

  function pick(id: string) {
    setClientId(id);
    setRequest(CLIENT_HINT[id]?.examples[0] ?? "");
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.startRun({ client_id: clientId, request, methods });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start");
      setBusy(false);
    }
  }

  const list = clients ?? Object.keys(CLIENT_HINT).map((id) => ({ client_id: id }) as Client);
  const learned = (prefs[clientId] ?? []).filter((p) => p.kind !== "note");

  return (
    <div className="rounded-[28px] border bg-card p-5 shadow-[0_20px_60px_-30px_rgba(26,22,20,0.25)] sm:p-7">
      {/* 1. client */}
      <p className="text-sm font-semibold">1. Who is the portfolio for?</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {list.map((c) => {
          const hint = CLIENT_HINT[c.client_id];
          const active = c.client_id === clientId;
          return (
            <button
              key={c.client_id}
              onClick={() => pick(c.client_id)}
              className={cn(
                "flex items-start gap-3 rounded-2xl border p-4 text-left transition-colors",
                active ? "border-accent bg-accent-soft/40" : "hover:bg-panel-2",
              )}
              aria-pressed={active}
            >
              <span
                className={cn(
                  "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border",
                  active && "border-accent bg-accent text-white",
                )}
              >
                {active && <Check className="size-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{c.name ?? c.client_id}</span>
                  {c.market && (
                    <span className="rounded-md bg-panel px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground">
                      {MARKET_LABEL[c.market]?.flag}
                    </span>
                  )}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {hint?.who}
                  {c.market_value !== undefined && ` · ${money(c.market_value, c.currency)}`}
                </span>
                <span className="mt-1 block text-sm">{hint?.rules}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <button onClick={() => setShowRules(clientId)} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
          <FileText className="size-3.5" /> Read this client&apos;s rules
        </button>
        {learned.length > 0 && (
          <span className="inline-flex items-center gap-1">
            <Brain className="size-3.5 text-accent" /> Remembers from your past reviews: {learned.map(prefText).join(", ")}
          </span>
        )}
      </div>

      {/* 2. question */}
      <p className="mt-6 text-sm font-semibold">2. What should the agents do?</p>
      <textarea
        value={request}
        onChange={(e) => setRequest(e.target.value)}
        rows={3}
        maxLength={2000}
        className="mt-3 w-full resize-none rounded-2xl border bg-panel-2 p-4 text-base outline-none focus:ring-2 focus:ring-accent"
        aria-label="Your request"
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {(CLIENT_HINT[clientId]?.examples ?? []).map((ex) => (
          <button
            key={ex}
            onClick={() => setRequest(ex)}
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-panel-2 hover:text-foreground"
          >
            {ex.length > 70 ? ex.slice(0, 68) + "…" : ex}
          </button>
        ))}
      </div>

      {/* options */}
      <button
        onClick={() => setShowOptions((v) => !v)}
        className="mt-5 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        aria-expanded={showOptions}
      >
        <ChevronDown className={cn("size-3.5 transition-transform", showOptions && "rotate-180")} /> Options
      </button>
      {showOptions && (
        <div className="mt-2 flex flex-wrap gap-2">
          {METHODS.map((m) => {
            const on = methods.includes(m);
            return (
              <button
                key={m}
                onClick={() => setMethods((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]))}
                disabled={m === "classical"}
                title={m === "classical" ? "Always on: the proven reference answer" : METHOD[m].explain}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs",
                  on ? "bg-foreground text-background" : "text-muted-foreground",
                )}
              >
                <span className="size-2 rounded-full" style={{ background: METHOD[m].color }} />
                {METHOD[m].name}
              </button>
            );
          })}
        </div>
      )}

      {error && <p className="mt-4 rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
      <Button size="lg" onClick={start} disabled={busy || !clients || request.trim().length < 3} className="mt-6 w-full">
        {busy ? <Loader2 className="size-4 animate-spin" /> : null}
        {busy ? "Starting…" : "Start"}
        {!busy && <ArrowRight className="size-4" />}
      </Button>
      <p className="mt-2 text-center text-xs text-subtle-foreground">
        About a minute. Nothing is traded until you approve. Practice account only.
      </p>
      {showRules && <RulesDialog clientId={showRules} onClose={() => setShowRules(null)} />}
    </div>
  );
}
