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

export type LLMCallRow = {
  id: string; run_id: string; stage: string; step: string; agent: string; role: string;
  model: string; profile: string; started_at: string; duration_ms: number;
  prompt_tokens: number; completion_tokens: number; finish_reason: string; status: string;
  error: string; attempt: number; temperature: number; max_tokens: number; think: boolean;
  schema_used: boolean; prompt_chars: number; response_chars: number; thinking_chars: number;
  system_prompt?: string; prompt?: string; response?: string; thinking?: string;
};

export type SpanRow = {
  id: string; kind: string; name: string; stage: string; step: string; agent: string;
  status: string; error: string; started_at: string; duration_ms: number;
  attributes: Record<string, any>; trace_id: string;
};

type Bucket = { calls: number; prompt_tokens: number; completion_tokens: number; seconds: number; errors: number; truncated: number };

export type Usage = {
  calls: number; prompt_tokens: number; completion_tokens: number; model_seconds: number;
  tokens_per_second: number; errors: number; truncated: number;
  by_model: Record<string, Bucket>; by_agent: Record<string, Bucket>;
  spans_by_kind: Record<string, { count: number; seconds: number; errors: number }>;
  stages: { stage: string; seconds: number; status: string; started_at: string }[];
};

export type Summary = {
  window_hours: number; runs_by_status: Record<string, number>;
  engine: { active: string[]; queued: string[]; limit: number };
  usage: Usage;
  per_run: { run_id: string; title: string; status?: string; calls: number; completion_tokens: number; model_seconds: number }[];
  activity?: {
    series: { at: string; calls: number; errors: number; tokens: number; seconds: number }[];
    bucket_seconds: number; gpu_busy_pct: number;
    latency: { p50: number; p90: number; p99: number; max: number };
  };
  recent_errors: { run_id: string; at: string; stage: string; agent: string; message: string }[];
  recent_runs: RunSummary[];
  models: { profile: string; models: Record<string, string>; ok: boolean; missing?: string[]; num_ctx?: number; think_roles?: string };
  integrations: { jira: boolean; git: boolean; otlp: boolean; vectors: boolean; plane?: boolean };
  links: Record<string, string>;
};

export type DeepHealth = {
  status: string;
  checks: { name: string; ok: boolean; ms: number; detail: string }[];
  integrations: Record<string, boolean>;
};

export type Integrations = {
  jira: { configured?: boolean; initiative?: { key?: string; url?: string }; sprint?: { name?: string };
          stories?: Record<string, { key?: string; url?: string }>; [k: string]: any };
  git: { configured?: boolean; url?: string; branch?: string; created?: boolean;
         pull_request?: { number?: number; url?: string }; release?: { tag?: string; default_branch?: string } };
};

export type KnowledgeStats = { graph: Record<string, number>; vectors: Record<string, number>; vectors_enabled: boolean };
export type Lesson = { id: string; lesson: string; applies_to: string; run_id: string; story_id: string; project?: string };
export type Recall = {
  graph: any[]; components: any[];
  stories: { run_id: string; project: string; title: string; outcome: string; score: number }[];
  lessons: { lesson: string; score: number }[];
  decisions: { title: string; decision: string; rationale: string; score: number }[];
};

export type CodemapStats = {
  files: number; loc: number; modules: number; screens: number; endpoints: number;
  story_endpoints: number; tables: number; classes: number; unserved_calls?: number;
  languages: Record<string, number>;
};
export type CodemapModule = {
  id: string; mid: string; name: string; kind: string; files: string[]; loc: number;
  capability?: string; stories?: string[]; subtitle?: string; summary?: string; responsibility?: string;
  endpoints?: string[]; tables?: string[]; flows?: string[]; l2?: string | null;
  calls?: { method: string; path: string; route: string | null }[];
};
export type CodemapFlow = {
  id: string; name: string; trigger: string; description: string; module: string; steps: number; mermaid: string;
};
export type CodemapAI = { status: string; model?: string; finished_at?: string; error?: string };
export type Codemap = {
  run_id: string; title: string; generated_at: string; git_ref: string; engine: string;
  ai: CodemapAI; stats: CodemapStats;
  views: { topology: string; modules: string; data: string };
  modules: CodemapModule[]; capabilities: Record<string, string[]>;
  flows: CodemapFlow[]; patterns: string[];
};
export type CodemapJob = { stage?: string; error?: string; running: boolean };
export type CodebaseRow = {
  run_id: string; title: string; status: string; created_at: string; analysed: boolean;
  generated_at?: string; git_ref?: string; engine?: string; ai?: CodemapAI; stats?: CodemapStats;
  preview?: string; patterns?: string[]; flows?: number; job: CodemapJob;
};

export type ConnectorSetting = { env: string; label: string; required: boolean; secret: boolean; set: boolean; value: string; help: string };
export type Connector = {
  name: string; title: string; category: string; description: string; vendor_url: string;
  mode: "live" | "sandbox" | "off"; missing: string[]; settings: ConnectorSetting[];
  operations: Record<string, string>; source: string; lines: number;
};
export type EnterpriseApp = {
  run_id: string; title: string; status: string; rules: number; workflows: number; roles: number;
  tests: { total?: number; passed?: number; failed?: number; untested?: string[] }; url: string | null;
};
export type EnterpriseCatalogue = {
  connectors: Connector[]; kernel: { key: string; title: string; detail: string }[];
  apps: EnterpriseApp[]; live_settings: string[];
};
export type DomainLayer = {
  imports: boolean; url: string | null;
  rules: { id: string; title: string; kind: string; source: string; where: string }[];
  workflows: { name: string; entity: string; field?: string; states: string[]; transitions: string[] }[];
  roles: Record<string, string>; personas: { username: string; full_name: string; title: string; roles: string[] }[];
  services: string[]; tests: { total?: number; passed?: number; failed?: number; untested?: string[] };
  problems: string[];
};

export type PlaneRef = { id: string; key?: string; url: string; identifier?: string; name?: string; stories?: string[] };
export type PlaneCounts = { backlog: number; unstarted: number; started: number; completed: number; cancelled: number };
export type PlaneIdea = {
  run_id: string; title: string; status: string; created_at: string;
  project: PlaneRef | null; sprint: PlaneRef | null; release: PlaneRef | null;
  stories: number; epics: number; counts: PlaneCounts | null;
};
export type PlaneCard = {
  id: string; key: string; name: string; priority: string | null; module: string | null; url: string;
  labels: { name: string; color: string | null }[];
};
export type PlaneBoard = {
  enabled: boolean; url: string; project: PlaneRef | null; sprint: PlaneRef | null; release: PlaneRef | null;
  epics: Record<string, PlaneRef>; stories: Record<string, PlaneRef>; total?: number;
  columns: { id: string; name: string; group: string; color: string | null; cards: PlaneCard[] }[];
};

export const api = {
  enterprise: () => json<EnterpriseCatalogue>("/api/enterprise/connectors"),
  runDomain: (id: string) => json<DomainLayer>(`/api/enterprise/runs/${id}/domain`),
  planeOverview: () => json<{ enabled: boolean; url: string; syncing: boolean; ideas: PlaneIdea[] }>("/api/plane"),
  planeBoard: (id: string) => json<PlaneBoard>(`/api/runs/${id}/plane`),
  planeSync: (id: string) => json<any>(`/api/runs/${id}/plane/sync`, { method: "POST" }),
  planeSyncAll: () => json<{ status: string }>("/api/plane/sync", { method: "POST" }),
  codebases: () => json<{ available: boolean; codebases: CodebaseRow[] }>("/api/codemaps"),
  codemap: (id: string) =>
    json<{ run_id: string; available: boolean; job: CodemapJob; map: Codemap | null }>(`/api/runs/${id}/codemap`),
  drawCodemap: (id: string, ai: boolean) =>
    json<{ status: string }>(`/api/runs/${id}/codemap?ai=${ai}`, { method: "POST" }),
  retryRun: (id: string) => json<{ id: string }>(`/api/runs/${id}/retry`, { method: "POST" }),
  cancelRun: (id: string) => json<{ id: string; outcome: string }>(`/api/runs/${id}/cancel`, { method: "POST" }),
  traces: (id: string) => json<{ calls: LLMCallRow[]; spans: SpanRow[] }>(`/api/runs/${id}/traces`),
  trace: (id: string, callId: string) => json<LLMCallRow>(`/api/runs/${id}/traces/${callId}`),
  usage: (id: string) => json<Usage>(`/api/runs/${id}/usage`),
  integrations: (id: string) => json<Integrations>(`/api/runs/${id}/integrations`),
  summary: (hours: number) => json<Summary>(`/api/observability/summary?hours=${hours}`),
  deepHealth: () => json<DeepHealth>("/health/deep"),
  knowledgeStats: () => json<KnowledgeStats>("/api/knowledge/stats"),
  lessons: () => json<Lesson[]>("/api/knowledge/lessons"),
  recall: (q: string) => json<Recall>(`/api/knowledge/recall?q=${encodeURIComponent(q)}`),
  reindex: () => json<{ status: string }>("/api/knowledge/reindex", { method: "POST" }),
  reindexStatus: () => json<{ status: string; error?: string; vectors?: Record<string, number> }>("/api/knowledge/reindex"),
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
