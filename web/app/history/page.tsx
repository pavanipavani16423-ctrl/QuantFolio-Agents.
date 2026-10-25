"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { RunsTable } from "@/components/home/recent-runs";
import { Accent, EmptyState, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

export default function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api.runs(100).then(setRuns).catch(() => setError(true));
  }, []);
  return (
    <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
      <SectionHeading
        eyebrow="History"
        title={
          <>
            Every request, <Accent>kept</Accent>.
          </>
        }
        lead="Each run keeps its full record: what every agent did, the sources, the scores and your decision."
      />
      <div className="mt-10">
        {error ? (
          <EmptyState>The backend is not reachable.</EmptyState>
        ) : runs ? (
          <RunsTable runs={runs} />
        ) : (
          <div className="grid place-items-center py-16 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
          </div>
        )}
      </div>
    </div>
  );
}
