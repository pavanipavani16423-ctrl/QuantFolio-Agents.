"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Brain, Check, FileText, Loader2, Plus, RotateCw, ShieldCheck, Trash2, X } from "lucide-react";
import { Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { MARKET_LABEL, riskWord } from "@/lib/plain";
import type { Client, ClientRules, Memory } from "@/lib/types";
import { prefText } from "@/components/run/memory";

const RULE_ROWS: { key: string; label: string; show: (r: ClientRules) => string }[] = [
  { key: "holdings", label: "Number of stocks", show: (r) => `exactly ${r.rules.holdings}` },
  { key: "max_weight", label: "Most in one stock", show: (r) => pct(r.rules.max_weight, 0) },
  { key: "min_weight", label: "Least in one stock", show: (r) => pct(r.rules.min_weight, 0) },
  { key: "max_sector_weight", label: "Most in one sector", show: (r) => pct(r.rules.max_sector_weight, 0) },
  { key: "max_volatility", label: "Largest ups and downs", show: (r) => `${pct(r.rules.max_volatility, 0)} a year` },
  {
    key: "risk_aversion",
    label: "Risk level",
    show: (r) => `${riskWord(r.rules.risk_aversion)} (setting ${r.rules.risk_aversion})`,
  },
  { key: "excluded_sectors", label: "Sectors not allowed", show: (r) => r.rules.excluded_sectors.join(", ") || "none" },
  {
    key: "excluded_tickers",
    label: "Companies not allowed",
    show: (r) => r.rules.excluded_tickers.map((t) => `${t} (${r.names[t] ?? t})`).join(", ") || "none",
  },
  {
    key: "approval_required",
    label: "Human approval",
    show: (r) => (r.rules.approval_required ? "required before any trade" : "not required"),
  },
];

function RulesDialog({ client, onClose }: { client: Client; onClose: () => void }) {
  const [rules, setRules] = useState<ClientRules | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api.clientRules(client.client_id).then(setRules).catch(() => setFailed(true));
  }, [client.client_id]);
  function showDoc() {
    setDoc("Loading…");
    api.mandate(client.client_id).then((m) => setDoc(m.text)).catch(() => setDoc("Could not load the document."));
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose} role="dialog" aria-modal>
      <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-3xl bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex items-center justify-between gap-4">
          <h3 className="text-lg font-semibold">{client.name}&apos;s rules</h3>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-panel" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          What the compliance agent reads from the client&apos;s policy document. Every plan is checked against these, and each
          rule shows where the document says so.
        </p>
        {failed && <p className="text-sm text-critical">Could not load the rules.</p>}
        {!rules && !failed && <p className="text-sm text-muted-foreground">Loading…</p>}
        {rules && (
          <ul className="divide-y divide-border rounded-2xl border">
            {RULE_ROWS.map((row) => {
              const quote = rules.rules.citations.find((c) => c.rule === row.key)?.quote;
              return (
                <li key={row.key} className="px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <span className="text-sm text-muted-foreground">{row.label}</span>
                    <span className="font-medium">{row.show(rules)}</span>
                  </div>
                  {quote && <p className="mt-1 text-xs italic text-subtle-foreground">“{quote}”</p>}
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-4">
          {doc === null ? (
            <button onClick={showDoc} className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">
              <FileText className="size-4" /> Show the full policy document
            </button>
          ) : (
            <pre className="whitespace-pre-wrap rounded-2xl bg-panel-2 p-4 font-sans text-sm leading-relaxed text-muted-foreground">{doc}</pre>
          )}
        </div>
      </div>
    </div>
  );
}

export function StartPanel() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clientId, setClientId] = useState("");
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [memory, setMemory] = useState<Record<string, Memory>>({});

  const load = useCallback((prefer?: string) => {
    api
      .clients()
      .then((cs) => {
        setClients(cs);
        const wanted = prefer ?? new URLSearchParams(window.location.search).get("client") ?? "C-102";
        const first = cs.find((c) => c.client_id === wanted) ?? cs[0];
        if (first) {
          setClientId(first.client_id);
          setRequest(first.examples[0] ?? "");
        }
        cs.forEach((c) =>
          api
            .memory(c.client_id)
            .then((m) => setMemory((cur) => ({ ...cur, [c.client_id]: m })))
            .catch(() => undefined),
        );
      })
      .catch(() => setLoadFailed(true));
  }, []);

  useEffect(() => load(), [load]);

  const current = clients?.find((c) => c.client_id === clientId);

  function pick(c: Client) {
    setClientId(c.client_id);
    setRequest(c.examples[0] ?? "");
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.startRun({ client_id: clientId, request });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start");
      setBusy(false);
    }
  }

  async function removeCurrent() {
    if (!current?.custom || !window.confirm(`Remove ${current.name}? Past plans stay in History.`)) return;
    try {
      await api.removeClient(current.client_id);
      load("C-102");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the client");
    }
  }

  const mem = memory[clientId];
  const remembered = mem
    ? [
        ...(mem.episodic[0] ? [`last review ${mem.episodic[0].outcome} on ${mem.episodic[0].when}`] : []),
        ...mem.semantic.map(prefText),
        ...(mem.procedural.length ? [`${mem.procedural.length} writing note${mem.procedural.length > 1 ? "s" : ""}`] : []),
      ]
    : [];

  async function forget() {
    await api.forgetClient(clientId).catch(() => undefined);
    const fresh = await api.memory(clientId).catch(() => undefined);
    if (fresh) setMemory((cur) => ({ ...cur, [clientId]: fresh }));
  }

  return (
    <div className="rounded-[28px] border bg-card p-5 shadow-[0_20px_60px_-30px_rgba(26,22,20,0.25)] sm:p-7">
      {/* 1. client */}
      <p className="text-sm font-semibold">1. Who is the portfolio for?</p>
      {loadFailed ? (
        <div className="mt-3 rounded-2xl bg-critical-soft p-4 text-sm text-critical">
          <p>Could not reach the backend. Start it with: uv run uvicorn app.main:app --port 8000</p>
          <Button
            variant="outline"
            onClick={() => {
              setLoadFailed(false);
              load();
            }}
            className="mt-3"
          >
            <RotateCw className="size-4" /> Try again
          </Button>
        </div>
      ) : (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {clients === null &&
            [0, 1, 2, 3].map((i) => <div key={i} className="h-[92px] animate-pulse rounded-2xl border bg-panel-2" aria-hidden />)}
          {clients?.map((c) => {
            const active = c.client_id === clientId;
            return (
              <button
                key={c.client_id}
                onClick={() => pick(c)}
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
                    <span className="truncate font-semibold">{c.name}</span>
                    <span className="flex shrink-0 gap-1">
                      {c.custom && (
                        <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-accent">
                          ADDED
                        </span>
                      )}
                      <span className="rounded-md bg-panel px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-muted-foreground">
                        {MARKET_LABEL[c.market]?.flag}
                      </span>
                    </span>
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {c.who} · {money(c.market_value, c.currency)}
                  </span>
                  <span className="mt-1 block text-sm">{c.rules_summary}</span>
                </span>
              </button>
            );
          })}
          {clients !== null && (
            <Link
              href="/clients/new"
              className="flex min-h-[92px] items-center justify-center gap-2 rounded-2xl border border-dashed p-4 text-sm font-medium text-muted-foreground hover:bg-panel-2 hover:text-foreground"
            >
              <Plus className="size-4" /> Add a client
            </Link>
          )}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {current && (
          <button onClick={() => setShowRules(true)} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
            <FileText className="size-3.5" /> Read {current.name}&apos;s rules
          </button>
        )}
        {current?.custom && (
          <button onClick={removeCurrent} className="inline-flex items-center gap-1 hover:text-critical">
            <Trash2 className="size-3.5" /> Remove client
          </button>
        )}
        {remembered.length > 0 && (
          <span className="inline-flex items-center gap-1">
            <Brain className="size-3.5 text-accent" /> Remembers: {remembered.join(" · ")}
            <button onClick={forget} className="ml-1 underline-offset-2 hover:text-foreground hover:underline">
              Forget
            </button>
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
        placeholder="Rebalance the portfolio. What are the main risks for … ?"
        className="mt-3 w-full resize-none rounded-2xl border bg-panel-2 p-4 text-base outline-none focus:ring-2 focus:ring-accent"
        aria-label="Your request"
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {(current?.examples ?? []).map((ex) => (
          <button
            key={ex}
            onClick={() => setRequest(ex)}
            className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-panel-2 hover:text-foreground"
          >
            {ex.length > 70 ? ex.slice(0, 68) + "…" : ex}
          </button>
        ))}
      </div>

      {error && <p className="mt-4 rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
      <Button size="lg" onClick={start} disabled={busy || !current || request.trim().length < 3} className="mt-6 w-full">
        {busy ? <Loader2 className="size-4 animate-spin" /> : null}
        {busy ? "Starting…" : "Start"}
        {!busy && <ArrowRight className="size-4" />}
      </Button>
      <p className="mt-2 text-center text-xs text-subtle-foreground">
        <ShieldCheck className="mr-1 inline size-3.5 text-good" />
        About 20 seconds. Personal details are removed and every step is safety-checked. Nothing is traded until you approve.
      </p>
      {showRules && current && <RulesDialog client={current} onClose={() => setShowRules(false)} />}
    </div>
  );
}
