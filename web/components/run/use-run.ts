"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "@/lib/api";
import type { Run, Step } from "@/lib/types";

const LIVE = new Set(["queued", "running"]);

/** The run document, kept live with Server-Sent Events (step events patch it in place;
 *  "update" and "status" events trigger a refetch of the full document). */
export function useRun(id: string) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refetch = useCallback(() => {
    if (refetchTimer.current) clearTimeout(refetchTimer.current);
    refetchTimer.current = setTimeout(() => {
      api.run(id).then(setRun).catch((e) => setError(String(e.message ?? e)));
    }, 150);
  }, [id]);

  useEffect(() => {
    api.run(id).then(setRun).catch((e) => setError(String(e.message ?? e)));
  }, [id]);

  const status = run?.status;
  const live = status ? LIVE.has(status) : false;

  useEffect(() => {
    if (!live) return;
    const source = new EventSource(eventsUrl(id));
    const onStep = (e: MessageEvent) => {
      const event = JSON.parse(e.data) as { data: Step & { key: string } };
      setRun((cur) =>
        cur ? { ...cur, steps: { ...cur.steps, [event.data.key]: { ...cur.steps[event.data.key], ...event.data } } } : cur,
      );
    };
    source.addEventListener("step", onStep);
    source.addEventListener("update", refetch);
    source.addEventListener("status", refetch);
    source.onerror = () => {
      // the browser reconnects by itself; also refresh in case the run finished meanwhile
      refetch();
    };
    return () => source.close();
  }, [id, live, refetch]);

  return { run, error, refetch, setRun };
}
