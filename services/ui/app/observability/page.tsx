"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type DeepHealth, type Summary } from "@/lib/api";
import { agent } from "@/lib/agents";
import { formatDuration } from "@/lib/progress";
import Icon from "@/components/Icon";
import { Columns, CountUp, Donut, Ring, Sparkline, colorFor } from "@/components/charts";

function tokens(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(Math.round(n));
}

function ago(iso: string | undefined, now: number): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const KIND_COLOR: Record<string, string> = {
  stage: "#0265DC", llm: "#4046CA", run: "#7E84FA", checks: "#0FB5AE", deploy: "#F68511",
  browser: "#DE3D82", sandbox: "#72E06A", kg: "#7326D3", git: "#8E8E8E",
};
const KIND_NOTE: Record<string, string> = {
  stage: "pipeline stages end to end", llm: "local model calls", run: "whole runs", checks: "platform checks",
  deploy: "compose up", browser: "real-browser checks", sandbox: "sandboxed test runs", kg: "knowledge graph", git: "commits and pushes",
};
const STATUS_TONE: Record<string, string> = {
  complete: "text-moss bg-moss/10", released: "text-moss bg-moss/10", running: "text-signal bg-signal/10",
  waiting: "text-ochre bg-ochre/10", held: "text-ochre bg-ochre/10", failed: "text-rust bg-rust/10",
  cancelled: "text-graphite bg-mist", queued: "text-graphite bg-mist",
};

function Kpi({ label, children, hint, spark, color, delay, icon }: {
  label: string; children: React.ReactNode; hint?: React.ReactNode; spark?: number[]; color?: string; delay: number; icon: string;
}) {
  return (
    <div className="enter spot relative overflow-hidden rounded-xl border border-rule bg-paper p-4 shadow-spectrum" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-2 text-[12px] text-graphite">
        <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${color ?? "#0265DC"}14`, color: color ?? "#0265DC" }}>
          <Icon name={icon} size={13} />
        </span>
        {label}
      </div>
      <p className="mt-2 text-[26px] font-semibold leading-none tracking-[-0.02em] tabular-nums">{children}</p>
      {hint && <p className="mt-1.5 text-[12px] text-graphite">{hint}</p>}
      {spark && spark.some((v) => v > 0) && <div className="mt-3 -mb-1"><Sparkline values={spark} color={color} height={30} /></div>}
    </div>
  );
}

function Card({ title, right, children, delay = 0, className = "" }: {
  title: string; right?: React.ReactNode; children: React.ReactNode; delay?: number; className?: string;
}) {
  return (
    <section className={`enter flex flex-col overflow-hidden rounded-xl border border-rule bg-paper shadow-spectrum ${className}`} style={{ animationDelay: `${delay}ms` }}>
      <header className="flex items-center gap-2 border-b border-rule px-4 py-3">
        <h2 className="text-[14px] font-semibold">{title}</h2>
        <div className="ml-auto">{right}</div>
      </header>
      <div className="flex-1">{children}</div>
    </section>
  );
}

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<DeepHealth | null>(null);
  const [hours, setHours] = useState(24);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [openError, setOpenError] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [s, h] = await Promise.all([api.summary(hours), api.deepHealth()]);
        if (!alive) return;
        setSummary(s);
        setHealth(h);
        setLoadedAt(Date.now());
        setError(null);
      } catch {
        if (alive) setError("The orchestrator is not answering on port 8080.");
      }
    };
    void load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [hours]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const u = summary?.usage;
  const act = summary?.activity;
  const kinds = useMemo(() => Object.entries(u?.spans_by_kind ?? {}).sort((a, b) => b[1].seconds - a[1].seconds), [u]);
  const agents = useMemo(() => Object.entries(u?.by_agent ?? {})
    .map(([k, v]) => {
      const info = agent(k);
      // Agents outside the cast (ArchiLens, the Data Designer) get a colour of their own, not grey.
      return { key: k, info: info.color === "#6E6E6E" ? { ...info, color: colorFor(k), name: info.name.replace(/^\w/, (c) => c.toUpperCase()) } : info, ...v };
    })
    .sort((a, b) => b.seconds - a.seconds), [u]);
  const errorsByRun = useMemo(() => {
    const out: { run_id: string; items: Summary["recent_errors"] }[] = [];
    for (const e of summary?.recent_errors ?? []) {
      const g = out.find((x) => x.run_id === e.run_id);
      if (g) g.items.push(e); else out.push({ run_id: e.run_id, items: [e] });
    }
    return out;
  }, [summary]);
  const titles = Object.fromEntries((summary?.per_run ?? []).map((r) => [r.run_id, r.title]));
  const maxRun = Math.max(...(summary?.per_run ?? []).map((r) => r.model_seconds), 1);
  const series = act?.series ?? [];
  const bucketLabel = (at: string, i: number) => {
    const every = Math.ceil(series.length / 6);
    if (i % every) return null;
    const d = new Date(at);
    return hours <= 72 ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const okChecks = health?.checks.filter((c) => c.ok).length ?? 0;

  return (
    <div className="space-y-6">
      <div className="enter flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Observability</h1>
          <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-graphite">
            Every model call, stage, sandbox run and deploy is timed and kept. The local model is the meter:
            its clock is the cost, and there is no token bill.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2 text-[12px] text-graphite">
            <span className="live-dot" /> Live{loadedAt ? ` · updated ${ago(new Date(loadedAt).toISOString(), now)}` : ""}
          </span>
          <div className="flex rounded-full border border-rule bg-mist p-0.5 text-[12.5px]">
            {[6, 24, 72, 168].map((h) => (
              <button key={h} type="button" onClick={() => setHours(h)}
                      className={`rounded-full px-3 py-1 transition ${hours === h ? "bg-paper font-medium text-ink shadow-spectrum" : "text-graphite hover:text-ink"}`}>
                {h < 48 ? `${h}h` : `${h / 24}d`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="text-[13px] text-rust">{error}</p>}

      {health && (
        <section className="enter flex flex-wrap items-stretch gap-2" style={{ animationDelay: "40ms" }}>
          <div className={`flex items-center gap-3 rounded-xl border px-4 py-2.5 ${health.status === "ok" ? "border-moss/30 bg-moss/[0.06]" : "border-ochre/40 bg-ochre/[0.07]"}`}>
            <span className={`grid h-8 w-8 place-items-center rounded-full text-white ${health.status === "ok" ? "bg-moss" : "bg-ochre"}`}>
              <Icon name={health.status === "ok" ? "check" : "alert"} size={16} strokeWidth={2.4} />
            </span>
            <div>
              <p className="text-[13px] font-semibold">{health.status === "ok" ? "All systems working" : "Something needs attention"}</p>
              <p className="text-[11.5px] text-graphite">{okChecks} of {health.checks.length} dependencies answering</p>
            </div>
          </div>
          {health.checks.map((c) => (
            <div key={c.name} title={c.detail}
                 className={`group flex min-w-[150px] flex-1 items-center gap-2.5 rounded-xl border px-3 py-2 ${c.ok ? "border-rule bg-paper" : "border-rust/40 bg-rust/[0.05]"}`}>
              <span className={`h-2 w-2 shrink-0 rounded-full ${c.ok ? "bg-moss" : "bg-rust"}`} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center text-[12.5px] font-medium">{c.name}<span className="ml-auto font-mono text-[11px] font-normal text-graphite">{c.ms}ms</span></p>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-mist">
                  <div className="bar-grow h-full rounded-full" style={{ width: `${Math.min(100, (c.ms / 200) * 100)}%`, background: c.ms > 150 ? "#E68619" : "#0FB5AE" }} />
                </div>
                <p className="mt-0.5 truncate text-[11px] text-graphite">{c.detail}</p>
              </div>
            </div>
          ))}
        </section>
      )}

      {!summary && !error && (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-[128px] rounded-xl" />)}</div>
      )}

      {summary && u && (
        <>
          <section className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Model calls" icon="spark" delay={60} color="#0265DC" spark={series.map((s) => s.calls)}
                 hint={<>{u.errors ? <span className="text-rust">{u.errors} failed</span> : "none failed"} · {u.truncated} truncated</>}>
              <CountUp value={u.calls} />
            </Kpi>
            <Kpi label="Tokens written" icon="file" delay={100} color="#4046CA" spark={series.map((s) => s.tokens)}
                 hint={`${tokens(u.prompt_tokens)} read`}>
              <CountUp value={u.completion_tokens} format={tokens} />
            </Kpi>
            <Kpi label="Model time" icon="clock" delay={140} color="#7E84FA" spark={series.map((s) => s.seconds)}
                 hint={`${u.tokens_per_second} tokens/s average`}>
              {formatDuration(u.model_seconds * 1000) || "0s"}
            </Kpi>
            <Kpi label="Response time" icon="flask" delay={180} color="#0FB5AE"
                 hint={act ? `p90 ${act.latency.p90}s · p99 ${act.latency.p99}s` : undefined}>
              {act ? <><CountUp value={act.latency.p50} format={(n) => n.toFixed(1)} /><span className="text-[15px] text-graphite">s median</span></> : "—"}
            </Kpi>
            <div className="enter flex items-center gap-3 rounded-xl border border-rule bg-paper p-4 shadow-spectrum" style={{ animationDelay: "220ms" }}>
              <Ring value={act?.gpu_busy_pct ?? 0} color="#F68511" size={70} label="GPU busy" />
              <div>
                <p className="text-[12px] text-graphite">GPU busy</p>
                <p className="text-[12px] leading-snug text-graphite">share of the window the local model was answering</p>
              </div>
            </div>
            <div className="enter flex items-center gap-3 rounded-xl border border-rule bg-paper p-4 shadow-spectrum" style={{ animationDelay: "260ms" }}>
              <span className={`grid h-12 w-12 place-items-center rounded-full text-[18px] font-semibold ${summary.engine.active.length ? "bg-signal text-white agent-live" : "bg-mist text-graphite"}`}
                    style={{ ["--agent" as any]: "#0265DC", ["--agent-glow" as any]: "#0265DC55" }}>
                {summary.engine.active.length}
              </span>
              <div>
                <p className="text-[12px] text-graphite">Engine</p>
                <p className="text-[13px] font-medium">{summary.engine.active.length ? "building now" : "idle"}</p>
                <p className="text-[11.5px] text-graphite">{summary.engine.queued.length} queued · limit {summary.engine.limit}</p>
              </div>
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card title="Model activity" delay={300}
                  right={<span className="flex items-center gap-3 text-[11.5px] text-graphite">
                    <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-signal" />calls</span>
                    <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rust" />failed</span>
                    <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-[#F68511]" />tokens</span>
                  </span>}>
              <div className="px-4 pb-3 pt-4">
                {series.some((s) => s.calls) ? (
                  <Columns series={series.map((s) => ({ ok: s.calls - s.errors, bad: s.errors, line: s.tokens, at: s.at }))} labels={bucketLabel} />
                ) : <p className="py-16 text-center text-[13px] text-graphite">No model calls in this window.</p>}
              </div>
            </Card>

            <Card title="Model time by agent" delay={340}>
              <div className="flex flex-col items-center gap-4 p-4 sm:flex-row lg:flex-col xl:flex-row">
                <Donut size={148} items={agents.map((a) => ({ label: a.info.name, value: a.seconds, color: a.info.color }))}
                       center={{ value: formatDuration(u.model_seconds * 1000) || "0s", label: "on the GPU" }} />
                <ul className="w-full min-w-0 flex-1 space-y-1.5 text-[12.5px]">
                  {agents.slice(0, 7).map((a) => (
                    <li key={a.key} className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: a.info.color }} />
                      <span className="min-w-0 flex-1 truncate">{a.info.name}</span>
                      <span className="font-mono text-[11px] text-graphite">{a.calls}×</span>
                      <span className="w-[52px] text-right font-mono text-[11px]">{formatDuration(a.seconds * 1000)}</span>
                    </li>
                  ))}
                  {!agents.length && <li className="text-graphite">No calls yet.</li>}
                </ul>
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Where the time goes" delay={380}>
              <ul className="space-y-3 p-4">
                {kinds.map(([k, v], i) => {
                  const max = kinds[0][1].seconds || 1;
                  const color = KIND_COLOR[k] ?? colorFor(k);
                  return (
                    <li key={k}>
                      <div className="flex items-baseline gap-2 text-[13px]">
                        <span className="font-medium">{k}</span>
                        <span className="truncate text-[11.5px] text-graphite">{KIND_NOTE[k] ?? ""}</span>
                        <span className="ml-auto shrink-0 font-mono text-[11.5px] text-graphite">
                          {v.count}× · {formatDuration(v.seconds * 1000) || "0s"}
                          {v.errors ? <span className="text-rust"> · {v.errors} failed</span> : null}
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-mist">
                        <div className="bar-grow h-full rounded-full" style={{ width: `${Math.max(1, (v.seconds / max) * 100)}%`, background: color, animationDelay: `${i * 60}ms` }} />
                      </div>
                    </li>
                  );
                })}
                {!kinds.length && <li className="text-[13px] text-graphite">Nothing timed in this window.</li>}
              </ul>
            </Card>

            <Card title="Runs in this window" delay={420}
                  right={<span className="text-[11.5px] text-graphite">{summary.per_run.length} with model calls</span>}>
              <ul className="divide-y divide-rule">
                {summary.per_run.sort((a, b) => b.model_seconds - a.model_seconds).map((r) => (
                  <li key={r.run_id} className="px-4 py-2.5">
                    <div className="flex items-center gap-2 text-[13px]">
                      <Link href={`/runs/${r.run_id}`} className="min-w-0 truncate font-medium hover:text-signal">{r.title || r.run_id}</Link>
                      <span className="font-mono text-[10.5px] text-graphite">{r.run_id.slice(0, 8)}</span>
                      {r.status && <span className={`rounded-full px-2 py-[1px] text-[10.5px] font-medium ${STATUS_TONE[r.status] ?? "bg-mist text-graphite"}`}>{r.status}</span>}
                      <span className="ml-auto shrink-0 font-mono text-[11.5px] text-graphite">{r.calls} calls · {tokens(r.completion_tokens)}</span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-mist">
                        <div className="bar-grow h-full rounded-full bg-gradient-to-r from-[#0265DC] to-[#7E84FA]" style={{ width: `${(r.model_seconds / maxRun) * 100}%` }} />
                      </div>
                      <span className="w-[56px] text-right font-mono text-[11px]">{formatDuration(r.model_seconds * 1000)}</span>
                    </div>
                  </li>
                ))}
                {!summary.per_run.length && <li className="px-4 py-6 text-center text-[13px] text-graphite">No runs used a model in this window.</li>}
              </ul>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card title="Recent errors" delay={460}
                  right={summary.recent_errors.length ? <span className="rounded-full bg-rust/10 px-2 py-0.5 text-[11px] font-medium text-rust">{summary.recent_errors.length}</span> : null}>
              {errorsByRun.length ? (
                <div className="divide-y divide-rule">
                  {errorsByRun.map((g) => (
                    <div key={g.run_id} className="px-4 py-3">
                      <div className="mb-1.5 flex items-center gap-2">
                        <Link href={`/runs/${g.run_id}`} className="text-[13px] font-semibold hover:text-signal">{titles[g.run_id] || "Run"}</Link>
                        <span className="font-mono text-[10.5px] text-graphite">{g.run_id}</span>
                        <span className="ml-auto text-[11px] text-graphite">{g.items.length} error{g.items.length === 1 ? "" : "s"}</span>
                      </div>
                      <ul className="space-y-1">
                        {g.items.map((e) => {
                          const idx = summary.recent_errors.indexOf(e);
                          const open = openError === idx;
                          const a = agent(e.agent || "system");
                          return (
                            <li key={idx}>
                              <button type="button" onClick={() => setOpenError(open ? null : idx)}
                                      className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] hover:bg-mist">
                                <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-rust" />
                                <span className={`min-w-0 flex-1 ${open ? "whitespace-pre-wrap break-words" : "truncate"}`}>{e.message}</span>
                                <span className="shrink-0 rounded-full px-1.5 text-[10.5px]" style={{ color: a.color, background: `${a.color}14` }}>{e.stage || a.name}</span>
                                <span className="w-[54px] shrink-0 text-right text-[11px] text-graphite">{ago(e.at, now)}</span>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid place-items-center px-4 py-10 text-center">
                  <span className="grid h-10 w-10 place-items-center rounded-full bg-moss/10 text-moss"><Icon name="check" size={18} /></span>
                  <p className="mt-2 text-[13px] text-graphite">No errors in this window.</p>
                </div>
              )}
            </Card>

            <div className="space-y-4">
              <Card title="Model" delay={500}>
                <div className="space-y-3 p-4">
                  {Object.entries(u.by_model).map(([m, v]) => (
                    <div key={m}>
                      <p className="truncate font-mono text-[12.5px] font-medium" title={m}>{m}</p>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                        {[["calls", String(v.calls)], ["written", tokens(v.completion_tokens)], ["tok/s", v.seconds ? (v.completion_tokens / v.seconds).toFixed(1) : "—"]].map(([l, val]) => (
                          <div key={l} className="rounded-lg bg-mist py-1.5">
                            <p className="text-[14px] font-semibold leading-none">{val}</p>
                            <p className="mt-0.5 text-[10.5px] text-graphite">{l}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-1.5 text-[11px]">
                    <span className="rounded-full bg-[#F5F9FF] px-2 py-0.5 text-signal">{summary.models.profile} profile</span>
                    {summary.models.num_ctx ? <span className="rounded-full bg-mist px-2 py-0.5 text-graphite">context {summary.models.num_ctx.toLocaleString()}</span> : null}
                    {summary.models.think_roles ? <span className="rounded-full bg-mist px-2 py-0.5 text-graphite">thinks for {summary.models.think_roles}</span> : null}
                    {summary.models.missing?.length ? <span className="rounded-full bg-rust/10 px-2 py-0.5 text-rust">missing {summary.models.missing.join(", ")}</span> : null}
                  </div>
                </div>
              </Card>
              <Card title="Runs by status" delay={540}>
                <div className="flex flex-wrap gap-1.5 p-4">
                  {Object.entries(summary.runs_by_status).sort((a, b) => b[1] - a[1]).map(([st, n]) => (
                    <span key={st} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium ${STATUS_TONE[st] ?? "bg-mist text-graphite"}`}>
                      {st} <b>{n}</b>
                    </span>
                  ))}
                </div>
              </Card>
            </div>
          </div>

          <section className="enter flex flex-wrap items-center gap-2 text-[13px]" style={{ animationDelay: "580ms" }}>
            <span className="mr-1 text-graphite">Deeper history:</span>
            {Object.entries(summary.links).map(([k, href]) => (
              <a key={k} href={href} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1.5 rounded-full border border-rule bg-paper px-3 py-1 capitalize transition hover:border-signal/50 hover:text-signal">
                {k} <Icon name="external" size={11} />
              </a>
            ))}
            <span className="ml-auto flex flex-wrap gap-1.5">
              {Object.entries(summary.integrations).map(([k, on]) => (
                <span key={k} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${on ? "bg-moss/10 text-moss" : "bg-mist text-graphite"}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${on ? "bg-moss" : "bg-rule"}`} />{k}
                </span>
              ))}
            </span>
          </section>
        </>
      )}
    </div>
  );
}
