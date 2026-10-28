import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui";
import type { Run } from "@/lib/types";

export function TechnicalDetails({ run }: { run: Run }) {
  return (
    <details className="group rounded-3xl border bg-card">
      <summary className="flex cursor-pointer items-center justify-between gap-3 p-5 sm:p-6">
        <span>
          <span className="block text-xl font-semibold tracking-tight">Technical details</span>
          <span className="block text-sm text-muted-foreground">
            Supervisor decisions, A2A messages, MCP tool calls and AI model calls. For engineers and reviewers.
          </span>
        </span>
        <ChevronDown className="size-5 transition-transform group-open:rotate-180" />
      </summary>
      <div className="flex flex-col gap-8 border-t p-5 sm:p-6">
        <div>
          <h3 className="mb-3 font-semibold">Supervisor decisions</h3>
          <ol className="flex flex-col gap-1.5 text-sm">
            {run.decisions.map((d, i) => (
              <li key={i} className="flex gap-3">
                <span className="tabular w-6 shrink-0 text-subtle-foreground">{i + 1}.</span>
                <span>
                  <span className="font-medium">{d.next.length ? d.next.join(" + ") : "finish"}</span>
                  <span className="text-muted-foreground"> · {d.reason}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div>
          <h3 className="mb-3 font-semibold">A2A messages ({run.a2a_calls.length})</h3>
          <ul className="flex flex-col gap-1.5 text-sm">
            {run.a2a_calls.map((c, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">{c.card ?? c.agent}</Badge>
                <span className="font-mono text-xs">{c.skill}</span>
                <span className="text-xs text-muted-foreground">
                  {c.url} · {c.transport === "http" ? "over HTTP" : "in-process"}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h3 className="mb-3 font-semibold">MCP tool calls ({run.tool_calls.length})</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3 font-medium">Agent</th>
                  <th className="py-1 pr-3 font-medium">Tool</th>
                  <th className="py-1 pr-3 font-medium">Status</th>
                  <th className="py-1 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {run.tool_calls.map((t, i) => (
                  <tr key={i} className="border-t">
                    <td className="py-1 pr-3">
                      {t.agent}
                      {t.via ? <span className="text-subtle-foreground"> ({t.via})</span> : null}
                    </td>
                    <td className="py-1 pr-3 font-mono">
                      {t.server}.{t.tool}
                    </td>
                    <td className="py-1 pr-3">{t.status}</td>
                    <td className="tabular py-1">{Math.round(t.latency_ms)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 className="mb-3 font-semibold">AI model calls ({run.llm_calls.length})</h3>
          {run.llm_calls.length ? (
            <ul className="flex flex-col gap-1 text-xs">
              {run.llm_calls.map((c, i) => (
                <li key={i}>
                  <span className="font-medium">{c.agent}</span> · {c.status}
                  {c.model ? ` · ${c.model}` : ""}
                  {c.latency_ms ? ` · ${Math.round(c.latency_ms)} ms` : ""}
                  {c.via ? ` · ${c.via}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">None.</p>
          )}
          <p className="mt-2 text-xs text-subtle-foreground">AI mode: {run.llm}</p>
        </div>
      </div>
    </details>
  );
}
