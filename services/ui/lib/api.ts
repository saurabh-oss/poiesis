export const API =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export type RunSummary = {
  id: string; title: string; status: string; stage: string;
  created_at: string; summary: Record<string, unknown>;
};

export type Artifact = {
  id: string; kind: string; stage: string; version: number;
  body: any; created_at: string;
};

export type Deployment = {
  run_id: string; title: string; project: string; port: number | null;
  url: string; status: string; detail: string;
  started_at: string | null; updated_at: string | null;
};

export type RunDetail = RunSummary & {
  evidence_count: number; artifacts: Artifact[]; files: string[];
  deployment: Deployment | null;
};

export type Stage = {
  key: string; label: string; description: string;
  agents: string[]; produces: string;
  gate: string | null; asks: string; gate_mode: string | null;
};

export type Evidence = {
  id: string; source_kind: string; source_ref: string; locator: string; content: string;
};

export type PoiesisEvent = {
  id?: string; at?: string; level: string; agent: string;
  stage: string; message: string; data: Record<string, any>;
};

export type Gate = {
  gate_id: string; kind: string; stage: string; question: string;
  artifact: any;
  options: { value: string; label: string }[];
  fields: { id: string; label: string; help?: string; placeholder?: string }[];
  default: { decision: string; notes: string };
};

export const api = {
  // Older orchestrators return only key/label/description; fill the rest so
  // components can rely on the shape.
  stages: () => json<Stage[]>("/api/runs/stages").then((list) =>
    list.map((s) => ({ ...s, agents: s.agents ?? [], produces: s.produces ?? "",
      gate: s.gate ?? null, asks: s.asks ?? "", gate_mode: s.gate_mode ?? null }))),
  health: () => json<{ status: string; llm_profile: string; pack: string }>("/health"),
  listRuns: () => json<RunSummary[]>("/api/runs"),
  getRun: (id: string) => json<RunDetail>(`/api/runs/${id}`),
  events: (id: string) => json<PoiesisEvent[]>(`/api/runs/${id}/events?limit=1500`),
  evidence: (id: string) => json<Evidence[]>(`/api/runs/${id}/evidence`),
  openGate: (id: string) =>
    json<{ open: boolean; gate?: Gate }>(`/api/runs/${id}/gates/open`),
  gateHistory: (id: string) => json<any[]>(`/api/runs/${id}/gates`),
  resolveGate: (id: string, body: any) =>
    json(`/api/runs/${id}/gates/resolve`, { method: "POST", body: JSON.stringify(body) }),
  createRun: (body: { title: string; sources: { kind: string; value: string; label?: string }[] }) =>
    json<{ id: string }>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  startRun: (id: string) => json<{ id: string }>(`/api/runs/${id}/start`, { method: "POST" }),
  deployments: () => json<Deployment[]>("/api/deployments"),
  deploy: (id: string) => json<{ status: string }>(`/api/runs/${id}/deploy`, { method: "POST" }),
  stopDeployment: (id: string) =>
    json<{ status: string }>(`/api/runs/${id}/deployment/stop`, { method: "POST" }),
  capabilities: () => json<any[]>("/api/knowledge/capabilities"),
  stack: () => json<any[]>("/api/knowledge/stack"),
  upload: async (id: string, files: File[] | FileList) => {
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    const res = await fetch(`${API}/api/runs/${id}/uploads`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};

export function socketFor(id: string) {
  const url = API.replace(/^http/, "ws");
  return new WebSocket(`${url}/ws/runs/${id}`);
}
