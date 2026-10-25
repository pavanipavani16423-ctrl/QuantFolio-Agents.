"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { Badge, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { METHOD, STATUS } from "@/lib/plain";
import type { RunSummary } from "@/lib/types";

export function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (!runs.length) return <EmptyState>No runs yet. Start one above.</EmptyState>;
  return (
    <div className="overflow-hidden rounded-3xl border bg-card">
      <ul className="divide-y">
        {runs.map((r) => (
          <li key={r.id}>
            <Link href={`/runs/${r.id}`} className="flex flex-col gap-2 px-5 py-4 hover:bg-panel-2 sm:flex-row sm:items-center sm:gap-6">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{r.client_name}</span>
                  <Badge tone={STATUS[r.status]?.tone}>{STATUS[r.status]?.label ?? r.status}</Badge>
                </div>
                <p className="mt-1 truncate text-sm text-muted-foreground">{r.request}</p>
              </div>
              <div className="flex shrink-0 items-center gap-4 text-sm text-muted-foreground">
                {r.recommended && <span>Picked by: {METHOD[r.recommended]?.short ?? r.recommended}</span>}
                <span>{ago(r.created_at)}</span>
                <ArrowUpRight className="size-4" />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RecentRuns() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  useEffect(() => {
    api.runs(5).then(setRuns).catch(() => setRuns([]));
  }, []);
  if (!runs || !runs.length) return null;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between">
        <h2 className="text-2xl font-semibold">Recent runs</h2>
        <Link href="/history" className="text-sm font-medium text-accent hover:underline">
          See all
        </Link>
      </div>
      <RunsTable runs={runs} />
    </div>
  );
}
