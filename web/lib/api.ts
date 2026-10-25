import type { ChangeRequest, Client, Preference, Run, RunSummary } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(API_KEY ? { "x-api-key": API_KEY } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export interface Health {
  status: string;
  llm: string;
  judge: string | null;
  langfuse: { enabled: boolean; host: string | null };
  rag_index_ready: boolean;
  runs: number;
  a2a_agents: Record<string, string>;
}

export interface SystemInfo {
  graph_mermaid: string;
  steps: { key: string; number: number; title: string; plain: string; type: string }[];
  a2a_agents: Record<
    string,
    { name: string; description: string; url: string; card_url: string; skills: { id: string; name: string; description: string }[] }
  >;
  mcp_servers: Record<string, { name: string; description: string }[]>;
  tool_permissions: Record<string, string[]>;
  scores: { name: string; type: string; description: string }[];
  settings: Record<string, unknown>;
}

export const api = {
  health: () => request<Health>("/health"),
  clients: () => request<Client[]>("/api/v1/clients"),
  account: (id: string) =>
    request<{ positions: Record<string, number>; weights: Record<string, number>; market_value: number; cash: number; sectors: Record<string, string> }>(
      `/api/v1/clients/${id}/account`,
    ),
  resetAccount: (id: string) => request(`/api/v1/clients/${id}/reset`, { method: "POST" }),
  runs: (limit = 30) => request<RunSummary[]>(`/api/v1/runs?limit=${limit}`),
  run: (id: string) => request<Run>(`/api/v1/runs/${id}`),
  startRun: (body: { client_id: string; request: string; methods: string[] }) =>
    request<Run>("/api/v1/runs", { method: "POST", body: JSON.stringify(body) }),
  decide: (
    id: string,
    body: { action: "approve" | "reject" | "change"; reviewer: string; note?: string; changes?: ChangeRequest; remember?: boolean },
  ) => request<Run>(`/api/v1/runs/${id}/approval`, { method: "POST", body: JSON.stringify(body) }),
  preferences: (clientId: string) => request<Preference[]>(`/api/v1/clients/${clientId}/preferences`),
  forgetPreference: (clientId: string, id: number) =>
    request(`/api/v1/clients/${clientId}/preferences/${id}`, { method: "DELETE" }),
  chunk: (id: string) => request<{ chunk_id: string; title: string; section: string; text: string; source_url: string | null }>(
    `/api/v1/chunks/${encodeURIComponent(id)}`,
  ),
  mandate: (clientId: string) => request<{ title: string; text: string }>(`/api/v1/mandates/${clientId}`),
  system: () => request<SystemInfo>("/api/v1/system"),
  evaluations: () => request<Record<string, unknown>>("/api/v1/evaluations"),
};

export function eventsUrl(runId: string, after = 0): string {
  const key = API_KEY ? `&api_key=${encodeURIComponent(API_KEY)}` : "";
  return `${API_URL}/api/v1/runs/${runId}/events?after=${after}${key}`;
}
