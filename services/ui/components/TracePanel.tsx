"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type LLMCallRow, type SpanRow, type Usage } from "@/lib/api";
import { agent } from "@/lib/agents";
import { formatDuration } from "@/lib/progress";
import AgentAvatar from "./AgentAvatar";
import Icon from "./Icon";

const STATUS: Record<string, string> = {
  ok: "border-moss/40 bg-moss/[0.07] text-moss",
  truncated: "border-ochre/50 bg-ochre/[0.08] text-ochre",
  unparseable: "border-ochre/50 bg-ochre/[0.08] text-ochre",
  error: "border-rust/40 bg-rust/[0.06] text-rust",
};

const KIND_TONE: Record<string, string> = {
  stage: "bg-signal", llm: "bg-[#8A3FD6]", sandbox: "bg-[#C8336E]", checks: "bg-[#0D8A80]",
  deploy: "bg-[#007A4D]", browser: "bg-[#DA7B11]", git: "bg-[#4F7F12]", jira: "bg-[#0B78B8]",
  kg: "bg-[#9A6B12]", run: "bg-rule",
};

function tokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function CallRow({ runId, call }: { runId: string; call: LLMCallRow }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<LLMCallRow | null>(null);
  const [tab, setTab] = useState<"prompt" | "response" | "thinking" | "system">("response");
  const a = agent(call.agent || call.role);

  async function toggle() {
    setOpen((o) => !o);
    if (!full) {
      try { setFull(await api.trace(runId, call.id)); } catch { /* shown as unavailable */ }
    }
  }

  const body = full ? (tab === "prompt" ? full.prompt : tab === "response" ? full.response
    : tab === "thinking" ? full.thinking : full.system_prompt) : "";

  return (
    <li className="rounded border border-rule bg-paper">
      <button type="button" onClick={toggle} className="flex w-full items-center gap-3 px-3 py-2 text-left">
        <AgentAvatar agentKey={call.agent || "system"} size={26} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px]">
            <span className="font-medium">{a.name}</span>
            <span className="text-graphite"> · {call.step || call.stage || "—"}</span>
          </p>
          <p className="truncate font-mono text-[11px] text-graphite">
            {call.model} · {tokens(call.prompt_tokens)} in / {tokens(call.completion_tokens)} out
            {call.think ? " · thought first" : ""}{call.schema_used ? " · schema" : ""}
            {call.attempt > 1 ? ` · attempt ${call.attempt}` : ""}
          </p>
        </div>
        <span className="font-mono text-[12px] tabular-nums text-graphite">{formatDuration(call.duration_ms)}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${STATUS[call.status] ?? STATUS.ok}`}>
          {call.status}
        </span>
        <Icon name="arrow" size={13} className={`text-graphite transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-rule px-3 py-2.5">
          {call.error && <p className="mb-2 text-[12px] text-rust">{call.error}</p>}
          <div className="mb-2 flex flex-wrap gap-1 text-[12px]">
            {(["response", "prompt", "system", "thinking"] as const).map((t) => (
              <button
                key={t} type="button" onClick={() => setTab(t)}
                className={`rounded border px-2 py-0.5 ${tab === t ? "border-signal bg-signal/[0.08] text-signal" : "border-rule text-graphite hover:text-ink"}`}
              >
                {t === "system" ? "system prompt" : t}
                {full && t === "prompt" ? ` · ${(full.prompt_chars / 1000).toFixed(1)}k chars` : ""}
              </button>
            ))}
          </div>
          <pre className="tape max-h-[420px] overflow-auto whitespace-pre-wrap rounded bg-mist p-2.5 font-mono text-[11px] leading-relaxed">
            {full ? (body || "(empty)") : "Loading…"}
          </pre>
        </div>
      )}
    </li>
  );
}

function Timeline({ spans }: { spans: SpanRow[] }) {
  const rows = spans.filter((s) => s.kind !== "run" && s.kind !== "llm");
  if (!rows.length) return null;
  const t0 = Math.min(...rows.map((s) => Date.parse(s.started_at)));
  const t1 = Math.max(...rows.map((s) => Date.parse(s.started_at) + s.duration_ms));
  const total = Math.max(1, t1 - t0);
  return (
    <div className="space-y-1">
      {rows.slice(-60).map((s) => {
        const left = ((Date.parse(s.started_at) - t0) / total) * 100;
        const width = Math.max(0.6, (s.duration_ms / total) * 100);
        return (
          <div key={s.id} className="grid grid-cols-[150px_minmax(0,1fr)_64px] items-center gap-2 text-[11.5px]">
            <span className="truncate text-graphite" title={`${s.kind}: ${s.name}`}>
              <span className="font-medium text-ink">{s.kind}</span> {s.name}
            </span>
            <div className="relative h-3 rounded bg-mist">
              <div
                className={`absolute top-0 h-3 rounded ${s.status === "error" ? "bg-rust" : KIND_TONE[s.kind] ?? "bg-signal"}`}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={s.error || s.name}
              />
            </div>
            <span className="text-right font-mono tabular-nums text-graphite">{formatDuration(s.duration_ms)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function TracePanel({ runId, active }: { runId: string; active: boolean }) {
  const [calls, setCalls] = useState<LLMCallRow[]>([]);
  const [spans, setSpans] = useState<SpanRow[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"calls" | "timeline">("calls");

  const refresh = useCallback(async () => {
    try {
      const [t, u] = await Promise.all([api.traces(runId), api.usage(runId)]);
      setCalls(t.calls);
      setSpans(t.spans);
      setUsage(u);
    } catch { /* the orchestrator will answer next time */ }
  }, [runId]);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);
  useEffect(() => {
    if (!open || !active) return;
    const timer = setInterval(() => { void refresh(); }, 8000);
    return () => clearInterval(timer);
  }, [open, active, refresh]);

  const byAgent = useMemo(() => Object.entries(usage?.by_agent ?? {}).sort((a, b) => b[1].seconds - a[1].seconds), [usage]);

  return (
    <details className="group rounded border border-rule bg-paper shadow-spectrum" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-[13px] font-medium [&::-webkit-details-marker]:hidden">
        <Icon name="arrow" size={13} className="text-graphite transition-transform group-open:rotate-90" />
        Model traces
        {usage && (
          <span className="ml-auto font-mono text-[12px] font-normal text-graphite">
            {usage.calls} calls · {tokens(usage.completion_tokens)} tokens out · {formatDuration(usage.model_seconds * 1000)} of model time
          </span>
        )}
      </summary>
      <div className="border-t border-rule px-4 py-3">
        {usage && usage.calls > 0 && (
          <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {byAgent.slice(0, 8).map(([key, v]) => {
              const a = agent(key);
              return (
                <div key={key} className="flex items-center gap-2 rounded border border-rule px-2.5 py-2">
                  <AgentAvatar agentKey={key} size={24} />
                  <div className="min-w-0">
                    <p className="truncate text-[12.5px] font-medium">{a.name}</p>
                    <p className="font-mono text-[11px] text-graphite">
                      {v.calls} calls · {tokens(v.completion_tokens)} out · {formatDuration(v.seconds * 1000)}
                      {v.errors ? ` · ${v.errors} failed` : ""}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div className="mb-2 flex gap-1 text-[12px]">
          {(["calls", "timeline"] as const).map((t) => (
            <button
              key={t} type="button" onClick={() => setView(t)}
              className={`rounded border px-2 py-0.5 ${view === t ? "border-signal bg-signal/[0.08] text-signal" : "border-rule text-graphite hover:text-ink"}`}
            >
              {t === "calls" ? `Model calls (${calls.length})` : `Timeline (${spans.length} spans)`}
            </button>
          ))}
        </div>
        {view === "calls" ? (
          calls.length ? (
            <ul className="space-y-1.5">{[...calls].reverse().map((c) => <CallRow key={c.id} runId={runId} call={c} />)}</ul>
          ) : (
            <p className="text-[13px] text-graphite">No model calls recorded for this run yet.</p>
          )
        ) : (
          <Timeline spans={spans} />
        )}
      </div>
    </details>
  );
}
