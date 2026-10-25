"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Check, FileText, Loader2, X } from "lucide-react";
import { Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { METHOD } from "@/lib/plain";
import type { Client } from "@/lib/types";

const CLIENT_HINT: Record<string, { who: string; rules: string; example: string }> = {
  "C-101": {
    who: "Retired teacher, 67",
    rules: "Low risk · exactly 10 stocks · max 15% each",
    example: "Rebalance Meera's portfolio. What risks could hurt the earnings of Johnson & Johnson and Coca-Cola?",
  },
  "C-102": {
    who: "Environmental charity",
    rules: "No oil & gas · exactly 8 stocks · max 20% each",
    example: "Rebalance the GreenLeaf endowment. What climate or environmental risks do NVIDIA and NextEra disclose?",
  },
  "C-103": {
    who: "Family office, 3 generations",
    rules: "No Pfizer · exactly 12 stocks · max 12% each",
    example: "Rebalance the Kumar family portfolio. What are the main risks for Apple and JPMorgan?",
  },
};

const METHODS = ["classical", "quantum", "hybrid"] as const;

function MandateDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    api.mandate(clientId).then((m) => setText(m.text)).catch(() => setText("Could not load the document."));
  }, [clientId]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose} role="dialog" aria-modal>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-3xl bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h3 className="text-lg font-semibold">Investment rules (synthetic example document)</h3>
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
  const [request, setRequest] = useState(CLIENT_HINT["C-102"].example);
  const [methods, setMethods] = useState<string[]>([...METHODS]);
  const [busy, setBusy] = useState(false);
  const [showRules, setShowRules] = useState<string | null>(null);

  useEffect(() => {
    api.clients().then(setClients).catch(() => setError("The backend is not reachable. Start it with: uv run uvicorn app.main:app"));
  }, []);

  function pick(id: string) {
    setClientId(id);
    setRequest(CLIENT_HINT[id]?.example ?? "");
  }

  function toggle(m: string) {
    setMethods((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.startRun({ client_id: clientId, request, methods });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the run");
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.15fr]">
      {/* clients */}
      <div className="flex flex-col gap-3">
        <p className="text-sm font-semibold text-muted-foreground">1 · Choose a client</p>
        {(clients ?? Object.keys(CLIENT_HINT).map((id) => ({ client_id: id }) as Client)).map((c) => {
          const hint = CLIENT_HINT[c.client_id];
          const active = c.client_id === clientId;
          return (
            <div
              key={c.client_id}
              className={cn(
                "rounded-3xl border bg-card p-5 transition-shadow",
                active ? "border-accent shadow-[0_0_0_3px_var(--accent-soft)]" : "hover:border-border-strong",
              )}
            >
              <button className="flex w-full items-start justify-between gap-4 text-left" onClick={() => pick(c.client_id)}>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{c.name ?? c.client_id}</span>
                    <span className="text-xs text-subtle-foreground">{c.client_id}</span>
                  </div>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {hint?.who} · {c.profile ?? ""}
                  </p>
                  <p className="mt-2 text-sm">{hint?.rules}</p>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className={cn("grid size-6 place-items-center rounded-full border", active && "border-accent bg-accent text-white")}>
                    {active && <Check className="size-3.5" />}
                  </span>
                  {c.market_value !== undefined && <span className="tabular text-sm text-muted-foreground">{money(c.market_value)}</span>}
                </div>
              </button>
              <button
                onClick={() => setShowRules(c.client_id)}
                className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
              >
                <FileText className="size-3.5" /> Read the rules document
              </button>
            </div>
          );
        })}
      </div>

      {/* request */}
      <div className="flex flex-col gap-3">
        <p className="text-sm font-semibold text-muted-foreground">2 · Write your request</p>
        <div className="flex flex-1 flex-col gap-4 rounded-3xl border bg-card p-5">
          <textarea
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            rows={5}
            maxLength={2000}
            className="w-full resize-none rounded-2xl bg-panel-2 p-4 text-base outline-none placeholder:text-subtle-foreground focus:ring-2 focus:ring-accent"
            placeholder="e.g. Rebalance the portfolio. What are the main risks for Apple?"
            aria-label="Your request"
          />
          <div>
            <p className="mb-2 text-sm font-semibold text-muted-foreground">3 · Which computers should try?</p>
            <div className="flex flex-wrap gap-2">
              {METHODS.map((m) => {
                const on = methods.includes(m);
                return (
                  <button
                    key={m}
                    onClick={() => toggle(m)}
                    disabled={m === "classical"}
                    title={m === "classical" ? "Always on: it is the reference answer" : METHOD[m].explain}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm",
                      on ? "border-transparent bg-foreground text-background" : "bg-card text-muted-foreground",
                    )}
                  >
                    <span className="size-2 rounded-full" style={{ background: METHOD[m].color }} />
                    {METHOD[m].name}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-subtle-foreground">
              The normal computer always runs: it is the proven reference the others are compared with.
            </p>
          </div>
          {error && <p className="rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
          <Button size="lg" onClick={start} disabled={busy || request.trim().length < 3} className="mt-auto w-full">
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {busy ? "Starting the agents…" : "Start the agents"}
            {!busy && <ArrowRight className="size-4" />}
          </Button>
        </div>
      </div>
      {showRules && <MandateDialog clientId={showRules} onClose={() => setShowRules(null)} />}
    </div>
  );
}
