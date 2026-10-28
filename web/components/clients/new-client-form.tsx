"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { CircleAlert, FileText, Loader2, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { Button, cn } from "@/components/ui";
import { api } from "@/lib/api";
import type { NewClient } from "@/lib/types";

type Asset = { ticker: string; name: string; sector: string };

const GOALS: { key: NewClient["goal"]; label: string; text: string }[] = [
  { key: "income", label: "Steady income", text: "Protect the money, modest growth" },
  { key: "balanced", label: "Balanced", text: "Growth and stability in equal parts" },
  { key: "growth", label: "Growth", text: "Grow the money over the long run" },
  { key: "esg", label: "Responsible growth", text: "Growth from responsible companies" },
];

// sensible starting rules per goal; the advisor can change every number
const PRESETS: Record<NewClient["goal"], Partial<NewClient>> = {
  income: { risk: "low", holdings: 10, max_weight: 0.15, min_weight: 0.04, max_sector_weight: 0.3, max_volatility: 0.18 },
  balanced: { risk: "medium", holdings: 10, max_weight: 0.15, min_weight: 0.04, max_sector_weight: 0.35, max_volatility: 0.22 },
  growth: { risk: "high", holdings: 8, max_weight: 0.2, min_weight: 0.05, max_sector_weight: 0.4, max_volatility: 0.28 },
  esg: { risk: "medium", holdings: 8, max_weight: 0.2, min_weight: 0.05, max_sector_weight: 0.4, max_volatility: 0.25, excluded_sectors: ["Energy"] },
};

const START: NewClient = {
  name: "",
  who: "",
  market: "US",
  goal: "balanced",
  risk: "medium",
  holdings: 10,
  max_weight: 0.15,
  min_weight: 0.04,
  max_sector_weight: 0.35,
  max_volatility: 0.22,
  horizon_years: 7,
  excluded_sectors: [],
  excluded_tickers: [],
  cash: 100000,
  positions: {},
  notes: "",
};

const input = "h-11 w-full rounded-xl border bg-card px-3 text-sm outline-none focus:ring-2 focus:ring-accent";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-subtle-foreground">{hint}</span>}
    </label>
  );
}

function Pct({ value, onChange, min, max }: { value: number; onChange: (v: number) => void; min: number; max: number }) {
  return (
    <div className="relative">
      <input
        type="number"
        min={min}
        max={max}
        step={0.5}
        value={Math.round(value * 1000) / 10}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className={cn(input, "pr-8")}
      />
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">%</span>
    </div>
  );
}

function Section({ n, title, lead, children }: { n: number; title: string; lead: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl border bg-card p-5 sm:p-6">
      <p className="text-sm font-semibold">
        {n}. {title}
      </p>
      <p className="mb-4 text-xs text-muted-foreground">{lead}</p>
      {children}
    </section>
  );
}

export function NewClientForm() {
  const router = useRouter();
  const [form, setForm] = useState<NewClient>(START);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [preview, setPreview] = useState<{ problems: string[]; policy: string; rules_summary: string } | null>(null);
  const [rows, setRows] = useState<{ ticker: string; shares: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof NewClient>(key: K, value: NewClient[K]) => setForm((f) => ({ ...f, [key]: value }));
  const sectors = useMemo(() => [...new Set(assets.map((a) => a.sector))].sort(), [assets]);
  const symbol = form.market === "IN" ? "₹" : "$";

  useEffect(() => {
    api.universe(form.market).then((u) => setAssets(u.assets)).catch(() => setAssets([]));
  }, [form.market]);

  // the rows on screen, and the positions they add up to
  function updateRows(next: { ticker: string; shares: number }[]) {
    const positions: Record<string, number> = {};
    next.forEach((r) => {
      if (r.ticker && r.shares > 0) positions[r.ticker] = (positions[r.ticker] ?? 0) + Math.floor(r.shares);
    });
    setRows(next);
    setForm((f) => ({ ...f, positions }));
  }

  // live preview of the policy document and of anything that would stop the rules from working
  useEffect(() => {
    const body = { ...form, name: form.name.trim().length >= 2 ? form.name : "New client" };
    const timer = setTimeout(() => {
      api.previewClient(body).then(setPreview).catch(() => undefined);
    }, 350);
    return () => clearTimeout(timer);
  }, [form]);

  function chooseMarket(market: NewClient["market"]) {
    setRows([]);
    setForm((f) => ({ ...f, market, positions: {}, excluded_tickers: [], cash: market === "IN" ? 5000000 : 100000 }));
  }

  function chooseGoal(goal: NewClient["goal"]) {
    setForm((f) => ({ ...f, goal, excluded_sectors: [], ...PRESETS[goal] }));
  }

  const toggle = (key: "excluded_sectors" | "excluded_tickers", v: string) =>
    setForm((f) => ({ ...f, [key]: f[key].includes(v) ? f[key].filter((x) => x !== v) : [...f[key], v] }));

  const problems = preview?.problems ?? [];
  const nameOk = form.name.trim().length >= 2;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const client = await api.createClient(form);
      router.push(`/?client=${client.client_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the client");
      setBusy(false);
    }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1.25fr_1fr]">
      <div className="flex flex-col gap-4">
        <Section n={1} title="About the client" lead="Who the portfolio is for and what it should achieve.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Client name">
              <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Rao Family" maxLength={80} className={input} />
            </Field>
            <Field label="Who they are" hint="One line, shown on the client card">
              <input value={form.who} onChange={(e) => set("who", e.target.value)} placeholder="e.g. Retired couple, Chennai" maxLength={60} className={input} />
            </Field>
          </div>
          <p className="mt-4 text-sm font-medium">Market</p>
          <div className="mt-1.5 flex gap-2">
            {(["US", "IN"] as const).map((m) => (
              <button
                key={m}
                onClick={() => chooseMarket(m)}
                className={cn("rounded-full border px-4 py-2 text-sm", form.market === m ? "border-accent bg-accent-soft text-accent" : "hover:bg-panel-2")}
                aria-pressed={form.market === m}
              >
                {m === "US" ? "United States (USD)" : "India (INR)"}
              </button>
            ))}
          </div>
          <p className="mt-4 text-sm font-medium">Goal</p>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
            {GOALS.map((g) => (
              <button
                key={g.key}
                onClick={() => chooseGoal(g.key)}
                className={cn("rounded-2xl border p-3 text-left", form.goal === g.key ? "border-accent bg-accent-soft/40" : "hover:bg-panel-2")}
                aria-pressed={form.goal === g.key}
              >
                <span className="block text-sm font-semibold">{g.label}</span>
                <span className="block text-xs text-muted-foreground">{g.text}</span>
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-subtle-foreground">Choosing a goal fills in typical rules below. You can change every one.</p>
          <div className="mt-4 max-w-[12rem]">
            <Field label="Time horizon (years)">
              <input type="number" min={1} max={40} value={form.horizon_years} onChange={(e) => set("horizon_years", Number(e.target.value))} className={input} />
            </Field>
          </div>
        </Section>

        <Section n={2} title="Money today" lead="Cash to invest and the shares the client already owns (optional).">
          <div className="max-w-xs">
            <Field label={`Cash (${symbol})`}>
              <input type="number" min={0} step={1000} value={form.cash} onChange={(e) => set("cash", Number(e.target.value))} className={input} />
            </Field>
          </div>
          <p className="mt-4 text-sm font-medium">Shares already owned</p>
          <div className="mt-1.5 flex flex-col gap-2">
            {rows.map((r, i) => (
              <div key={i} className="flex gap-2">
                <select
                  value={r.ticker}
                  onChange={(e) => updateRows(rows.map((x, j) => (j === i ? { ...x, ticker: e.target.value } : x)))}
                  className={cn(input, "flex-1")}
                  aria-label="Company"
                >
                  <option value="">Choose a company</option>
                  {assets.map((a) => (
                    <option key={a.ticker} value={a.ticker}>
                      {a.name} ({a.ticker})
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  min={1}
                  value={r.shares || ""}
                  placeholder="Shares"
                  onChange={(e) => updateRows(rows.map((x, j) => (j === i ? { ...x, shares: Number(e.target.value) } : x)))}
                  className={cn(input, "w-28")}
                  aria-label="Number of shares"
                />
                <button
                  onClick={() => updateRows(rows.filter((_, j) => j !== i))}
                  className="grid size-11 shrink-0 place-items-center rounded-xl border hover:bg-panel-2"
                  aria-label="Remove this holding"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
            <button
              onClick={() => updateRows([...rows, { ticker: "", shares: 0 }])}
              className="inline-flex w-fit items-center gap-1 text-sm font-medium text-accent hover:underline"
            >
              <Plus className="size-4" /> Add a holding
            </button>
          </div>
        </Section>

        <Section n={3} title="The client's rules" lead="Limits every plan must respect. The compliance agent checks each one.">
          <p className="text-sm font-medium">Risk level</p>
          <div className="mt-1.5 flex gap-2">
            {(["low", "medium", "high"] as const).map((r) => (
              <button
                key={r}
                onClick={() => set("risk", r)}
                className={cn("rounded-full border px-4 py-2 text-sm capitalize", form.risk === r ? "border-accent bg-accent-soft text-accent" : "hover:bg-panel-2")}
                aria-pressed={form.risk === r}
              >
                {r}
              </button>
            ))}
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Field label="Number of stocks" hint="3 to 15">
              <input type="number" min={3} max={15} value={form.holdings} onChange={(e) => set("holdings", Number(e.target.value))} className={input} />
            </Field>
            <Field label="Most in one stock">
              <Pct value={form.max_weight} onChange={(v) => set("max_weight", v)} min={5} max={50} />
            </Field>
            <Field label="Least in one stock">
              <Pct value={form.min_weight} onChange={(v) => set("min_weight", v)} min={1} max={20} />
            </Field>
            <Field label="Most in one sector">
              <Pct value={form.max_sector_weight} onChange={(v) => set("max_sector_weight", v)} min={10} max={100} />
            </Field>
            <Field label="Largest yearly ups and downs" hint="Expected volatility">
              <Pct value={form.max_volatility} onChange={(v) => set("max_volatility", v)} min={5} max={60} />
            </Field>
          </div>
          <p className="mt-5 text-sm font-medium">Sectors not allowed</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {sectors.map((s) => {
              const on = form.excluded_sectors.includes(s);
              return (
                <button
                  key={s}
                  onClick={() => toggle("excluded_sectors", s)}
                  className={cn("rounded-full border px-3 py-1 text-sm", on ? "border-critical bg-critical-soft text-critical" : "hover:bg-panel-2")}
                  aria-pressed={on}
                >
                  {s}
                </button>
              );
            })}
          </div>
          <p className="mt-4 text-sm font-medium">Companies not allowed</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {assets.map((a) => {
              const on = form.excluded_tickers.includes(a.ticker);
              return (
                <button
                  key={a.ticker}
                  onClick={() => toggle("excluded_tickers", a.ticker)}
                  title={a.name}
                  className={cn("rounded-full border px-3 py-1 text-sm", on ? "border-critical bg-critical-soft text-critical" : "hover:bg-panel-2")}
                  aria-pressed={on}
                >
                  {a.ticker}
                </button>
              );
            })}
          </div>
          <div className="mt-5">
            <Field label="Notes for the agents (optional)" hint="e.g. Prefers companies that pay steady dividends. Personal details are removed.">
              <textarea
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
                maxLength={600}
                rows={3}
                className="w-full resize-none rounded-xl border bg-card p-3 text-sm outline-none focus:ring-2 focus:ring-accent"
              />
            </Field>
          </div>
        </Section>
      </div>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-24">
        <section className="rounded-3xl border bg-card p-5 sm:p-6">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <FileText className="size-4 text-accent" /> The policy document the agents will read
          </p>
          <p className="mb-3 text-xs text-muted-foreground">
            Your answers are written up as the client&apos;s investment policy. The compliance agent finds the rules in it with
            search, exactly as for the other clients.
          </p>
          {preview?.rules_summary && <p className="mb-3 rounded-xl bg-panel-2 px-3 py-2 text-sm font-medium">{preview.rules_summary}</p>}
          <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-2xl bg-panel-2 p-4 font-sans text-xs leading-relaxed text-muted-foreground">
            {preview?.policy ?? "Loading…"}
          </pre>
        </section>
        {problems.length > 0 && (
          <div className="rounded-2xl bg-warning-soft p-4 text-sm">
            <p className="flex items-center gap-2 font-semibold text-warning">
              <CircleAlert className="size-4" /> These rules cannot work yet
            </p>
            <ul className="mt-2 list-disc pl-5 text-foreground">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="rounded-xl bg-critical-soft p-3 text-sm text-critical">{error}</p>}
        <Button size="lg" onClick={create} disabled={busy || !nameOk || problems.length > 0 || !preview}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />} Add client
        </Button>
        <p className="text-center text-xs text-subtle-foreground">
          <ShieldCheck className="mr-1 inline size-3.5 text-good" />
          {nameOk ? "Every plan for this client will need your approval." : "Type the client's name to continue."}
        </p>
      </aside>
    </div>
  );
}
