"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";
import { Accent, Badge, Card, EmptyState, SectionHeading } from "@/components/ui";
import { api, type SystemInfo } from "@/lib/api";

const PLAIN = [
  {
    title: "What it is",
    body: "A team of AI agents that does a portfolio manager's quarterly routine: read company reports, apply the client's rules, choose stocks, check the result and write a memo, then wait for a person to approve.",
  },
  {
    title: "Who it helps",
    body: "Wealth managers and advisors who rebalance many client portfolios, and compliance teams who must prove that every rule was read, checked and approved, with a record of who decided what.",
  },
  {
    title: "Why you can trust it",
    body: "Safety checks guard every place text comes in or goes out, every claim cites its source, trades need your signed approval, and the team remembers your feedback for next time.",
  },
];

const FLOW: { keys: string[]; label: string }[] = [
  { keys: ["guard", "intake"], label: "Check and understand" },
  { keys: ["research", "risk", "mandate"], label: "Gather (in parallel)" },
  { keys: ["optimize"], label: "Choose stocks" },
  { keys: ["backtest", "check"], label: "Test and check" },
  { keys: ["report", "evaluate"], label: "Explain and score" },
  { keys: ["trades", "approval", "execute"], label: "Human approval" },
];

const LAYERS: { title: string; items: string[] }[] = [
  {
    title: "Guardrails",
    items: [
      "Input: personal data removed; hidden instructions (patterns + meaning); scope policy",
      "Documents: passages that read like instructions are set aside; sources marked as data",
      "Output: citations exist and support each claim; numbers match facts; no promises",
      "Action: broker order limits; signed, single-use approval token",
    ],
  },
  {
    title: "Memory",
    items: [
      "Working: the saved state of every step (survives restarts)",
      "Episodic: what happened in past reviews of a client",
      "Semantic: learned preferences (they only tighten the rules)",
      "Procedural: your notes, reused as writing guidance; plus a research answer cache",
    ],
  },
  {
    title: "Reliability",
    items: [
      "Self-correction: a failed check gets one rewrite with the reasons, then a safe fallback",
      "Retries with jittered backoff; a circuit breaker skips a failing AI provider",
      "Idempotent trades; durable pause for approval; tool-call budget per run",
      "Hash-chained audit log; rate limits; security headers",
    ],
  },
];

const STACK = [
  "LangGraph (supervisor + interrupt)",
  "A2A protocol 1.0 (a2a-sdk)",
  "MCP (4 servers, per-agent permissions)",
  "Hybrid RAG: BM25 + embeddings + RRF + cross-encoder",
  "Guardrails: OWASP LLM Top 10 mapping",
  "Memory: working, episodic, semantic, procedural",
  "Langfuse tracing + scores",
  "RAGAS 0.4 evaluation",
  "Groq / OpenAI / Anthropic LLMs",
  "FastAPI + SSE",
  "SQLAlchemy + SQLite/Postgres",
  "Next.js 16 + React 19",
];

export function SystemView() {
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api.system().then(setSys).catch(() => setError(true));
  }, []);
  const stepTitle = (k: string) => sys?.steps.find((s) => s.key === k);

  return (
    <div className="mt-16 flex flex-col gap-24">
      <div className="grid gap-4 md:grid-cols-3">
        {PLAIN.map((p) => (
          <Card key={p.title}>
            <h2 className="text-lg font-semibold">{p.title}</h2>
            <p className="mt-2 text-muted-foreground">{p.body}</p>
          </Card>
        ))}
      </div>

      {error && <EmptyState>The backend is not reachable, so the live architecture cannot be shown.</EmptyState>}
      {!sys && !error && (
        <div className="grid place-items-center py-10 text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      )}

      {sys && (
        <>
          <section>
            <SectionHeading
              eyebrow="The flow"
              title={
                <>
                  A supervisor <Accent>decides</Accent> who works next.
                </>
              }
              lead="LangGraph runs the agents as a graph. Independent work runs at the same time. If the risk limit fails, the supervisor sends the optimizer back with a stricter setting. The run pauses durably before any trade until a person approves."
            />
            <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FLOW.map((group, i) => (
                <div key={group.label} className="flex">
                  <div className="flex flex-1 flex-col gap-2 rounded-3xl bg-panel p-3">
                    <p className="flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-accent">
                      <span className="accent-word text-xl normal-case">{i + 1}</span> {group.label}
                    </p>
                    {group.keys.map((k) => {
                      const s = stepTitle(k);
                      return (
                        <div key={k} className="rounded-2xl bg-card p-3">
                          <p className="text-sm font-medium">{s?.plain ?? k}</p>
                          <p className="mt-0.5 text-[11px] text-subtle-foreground">
                            {s ? `${String(s.number).padStart(2, "0")} · ${s.type}` : ""}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <SectionHeading
              eyebrow="Safe by design"
              title={
                <>
                  Guardrails, memory and <Accent>reliability</Accent>.
                </>
              }
              lead="Each layer is a set of plain rules or stores with its own tests, so it can be checked and explained."
            />
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {LAYERS.map((l) => (
                <Card key={l.title}>
                  <h3 className="text-lg font-semibold">{l.title}</h3>
                  <ul className="mt-3 flex flex-col gap-2 text-sm text-muted-foreground">
                    {l.items.map((i) => (
                      <li key={i}>{i}</li>
                    ))}
                  </ul>
                </Card>
              ))}
            </div>
          </section>

          <section>
            <SectionHeading
              eyebrow="A2A"
              title={
                <>
                  Agents from <Accent>other teams</Accent>.
                </>
              }
              lead="The risk and compliance agents are separate services that publish an Agent Card and accept tasks over the A2A protocol (JSON-RPC). The caller passes its Langfuse trace id, so their work shows up inside the same trace."
            />
            <div className="mt-10 grid gap-4 md:grid-cols-2">
              {Object.entries(sys.a2a_agents).map(([key, a]) => (
                <Card key={key}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">{a.name}</h3>
                      <p className="text-sm text-muted-foreground">{a.description}</p>
                    </div>
                    <Badge tone="accent">A2A 1.0</Badge>
                  </div>
                  <ul className="mt-4 flex flex-col gap-2">
                    {a.skills.map((s) => (
                      <li key={s.id} className="rounded-2xl bg-panel-2 p-3 text-sm">
                        <span className="font-mono text-xs text-accent">{s.id}</span>
                        <p className="mt-0.5 text-muted-foreground">{s.description}</p>
                      </li>
                    ))}
                  </ul>
                  <a href={a.card_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
                    View the Agent Card <ExternalLink className="size-3.5" />
                  </a>
                </Card>
              ))}
            </div>
          </section>

          <section>
            <SectionHeading
              eyebrow="MCP"
              title={
                <>
                  Tools behind <Accent>clear permissions</Accent>.
                </>
              }
              lead="Four MCP servers hold the data and the heavy computation. Each agent may only call the tools it needs."
            />
            <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {Object.entries(sys.mcp_servers).map(([server, tools]) => (
                <Card key={server} className="p-5">
                  <h3 className="font-semibold capitalize">{server}</h3>
                  <ul className="mt-3 flex flex-col gap-2">
                    {tools.map((t) => (
                      <li key={t.name}>
                        <span className="font-mono text-xs">{t.name}</span>
                        <p className="text-xs text-muted-foreground">{t.description}</p>
                      </li>
                    ))}
                  </ul>
                </Card>
              ))}
            </div>
            <div className="mt-4 overflow-x-auto rounded-3xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-panel-2 text-left text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Agent</th>
                    <th className="px-4 py-2 font-medium">Allowed tools</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(sys.tool_permissions).map(([agent, perms]) => (
                    <tr key={agent} className="border-t">
                      <td className="px-4 py-2 font-medium">{agent}</td>
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{perms.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <SectionHeading
              eyebrow="Observability"
              title={
                <>
                  Every score, <Accent>on the dashboard</Accent>.
                </>
              }
              lead="Each run is one Langfuse trace with a numbered section per agent. These scores are attached to it, so quality can be filtered and charted over time."
            />
            <div className="mt-10 overflow-x-auto rounded-3xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-panel-2 text-left text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Score</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {sys.scores.map((s) => (
                    <tr key={s.name} className="border-t align-top">
                      <td className="px-4 py-2 font-mono text-xs">{s.name}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">{s.type}</td>
                      <td className="px-4 py-2 text-muted-foreground">{s.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <SectionHeading eyebrow="Stack" title="Built with" />
            <div className="mt-8 flex flex-wrap gap-2">
              {STACK.map((s) => (
                <span key={s} className="rounded-full border bg-card px-4 py-2 text-sm">
                  {s}
                </span>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
