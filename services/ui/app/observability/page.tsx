"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type DeepHealth, type Summary } from "@/lib/api";
import { formatDuration } from "@/lib/progress";
import Icon from "@/components/Icon";

function tokens(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border border-rule bg-paper px-4 py-3 shadow-spectrum">
      <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-graphite">{label}</p>
      <p className="mt-1 font-mono text-[22px] font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[12px] text-graphite">{hint}</p>}
    </div>
  );
}

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<DeepHealth | null>(null);
  const [hours, setHours] = useState(24);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [s, h] = await Promise.all([api.summary(hours), api.deepHealth()]);
        if (!alive) return;
        setSummary(s);
        setHealth(h);
        setError(null);
      } catch {
        if (alive) setError("The orchestrator is not answering on port 8080.");
      }
    };
    void load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [hours]);

  const u = summary?.usage;
  const models = Object.entries(u?.by_model ?? {});
  const kinds = Object.entries(u?.spans_by_kind ?? {}).sort((a, b) => b[1].seconds - a[1].seconds);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Observability</h1>
          <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-graphite">
            Every model call, stage, sandbox run and deploy is timed and kept. This page reads the
            same records the run pages do; the tracing and metrics backends hold the long history.
          </p>
        </div>
        <div className="flex items-center gap-1 text-[12px]">
          {[6, 24, 72, 168].map((h) => (
            <button key={h} type="button" onClick={() => setHours(h)}
              className={`rounded border px-2.5 py-1 ${hours === h ? "border-signal bg-signal/[0.08] text-signal" : "border-rule text-graphite hover:text-ink"}`}>
              {h < 48 ? `${h}h` : `${h / 24}d`}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-[13px] text-rust">{error}</p>}

      {health && (
        <section>
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-semibold">Dependencies</h2>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${health.status === "ok" ? "border-moss/40 bg-moss/[0.07] text-moss" : "border-ochre/50 bg-ochre/[0.08] text-ochre"}`}>
              {health.status}
            </span>
          </div>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {health.checks.map((c) => (
              <li key={c.name} className={`flex items-start gap-2.5 rounded border px-3 py-2.5 ${c.ok ? "border-rule bg-paper" : "border-rust/40 bg-rust/[0.04]"}`}>
                <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-paper ${c.ok ? "bg-moss" : "bg-rust"}`}>
                  <Icon name={c.ok ? "check" : "x"} size={11} strokeWidth={2.6} />
                </span>
                <div className="min-w-0">
                  <p className="text-[13px] font-medium">{c.name} <span className="font-mono text-[11px] font-normal text-graphite">{c.ms}ms</span></p>
                  <p className="truncate text-[12px] text-graphite" title={c.detail}>{c.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {summary && u && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Model calls" value={String(u.calls)} hint={`${u.errors} failed · ${u.truncated} truncated`} />
            <Stat label="Tokens out" value={tokens(u.completion_tokens)} hint={`${tokens(u.prompt_tokens)} in`} />
            <Stat label="Model time" value={formatDuration(u.model_seconds * 1000) || "0s"} hint={`${u.tokens_per_second} tokens/s average`} />
            <Stat label="Engine" value={`${summary.engine.active.length} / ${summary.engine.limit}`} hint={`${summary.engine.queued.length} queued · limit ${summary.engine.limit}`} />
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded border border-rule bg-paper shadow-spectrum">
              <h2 className="border-b border-rule px-4 py-2.5 text-[13px] font-medium">Models</h2>
              <table className="w-full text-[13px]">
                <thead className="text-left text-[11px] uppercase tracking-[0.06em] text-graphite">
                  <tr><th className="px-4 py-2">Model</th><th className="px-2 py-2 text-right">Calls</th><th className="px-2 py-2 text-right">Out</th><th className="px-2 py-2 text-right">Time</th><th className="px-4 py-2 text-right">tok/s</th></tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {models.map(([m, v]) => (
                    <tr key={m}>
                      <td className="px-4 py-2 font-mono text-[12px]">{m}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{v.calls}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{tokens(v.completion_tokens)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{formatDuration(v.seconds * 1000)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{v.seconds ? (v.completion_tokens / v.seconds).toFixed(1) : "—"}</td>
                    </tr>
                  ))}
                  {!models.length && <tr><td colSpan={5} className="px-4 py-3 text-graphite">No model calls in this window.</td></tr>}
                </tbody>
              </table>
              <div className="border-t border-rule px-4 py-2.5 text-[12px] text-graphite">
                {summary.models.profile} profile
                {summary.models.missing?.length ? <span className="text-rust"> · missing: {summary.models.missing.join(", ")}</span> : null}
                {"num_ctx" in summary.models ? ` · context ${summary.models.num_ctx} · thinking for ${summary.models.think_roles}` : ""}
              </div>
            </section>

            <section className="rounded border border-rule bg-paper shadow-spectrum">
              <h2 className="border-b border-rule px-4 py-2.5 text-[13px] font-medium">Where the time goes</h2>
              <ul className="divide-y divide-rule">
                {kinds.map(([k, v]) => {
                  const max = kinds[0][1].seconds || 1;
                  return (
                    <li key={k} className="px-4 py-2">
                      <div className="flex justify-between text-[13px]"><span>{k}</span><span className="font-mono text-[12px] text-graphite">{v.count} · {formatDuration(v.seconds * 1000)}{v.errors ? ` · ${v.errors} failed` : ""}</span></div>
                      <div className="mt-1 h-1.5 rounded-full bg-mist"><div className="h-full rounded-full bg-signal" style={{ width: `${(v.seconds / max) * 100}%` }} /></div>
                    </li>
                  );
                })}
                {!kinds.length && <li className="px-4 py-3 text-[13px] text-graphite">Nothing timed in this window.</li>}
              </ul>
            </section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded border border-rule bg-paper shadow-spectrum">
              <h2 className="border-b border-rule px-4 py-2.5 text-[13px] font-medium">Runs in this window</h2>
              <ul className="divide-y divide-rule">
                {summary.per_run.map((r) => (
                  <li key={r.run_id} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]">
                    <Link href={`/runs/${r.run_id}`} className="min-w-0 truncate hover:text-signal">{r.title || r.run_id}</Link>
                    <span className="shrink-0 font-mono text-[12px] text-graphite">{r.calls} calls · {tokens(r.completion_tokens)} · {formatDuration(r.model_seconds * 1000)}</span>
                  </li>
                ))}
                {!summary.per_run.length && <li className="px-4 py-3 text-[13px] text-graphite">No runs used a model in this window.</li>}
              </ul>
            </section>
            <section className="rounded border border-rule bg-paper shadow-spectrum">
              <h2 className="border-b border-rule px-4 py-2.5 text-[13px] font-medium">Recent errors</h2>
              <ul className="divide-y divide-rule">
                {summary.recent_errors.map((e, i) => (
                  <li key={i} className="px-4 py-2 text-[12.5px]">
                    <Link href={`/runs/${e.run_id}`} className="font-mono text-[11px] text-signal">{e.run_id}</Link>
                    <span className="text-graphite"> · {e.stage} · {e.agent}</span>
                    <p className="truncate" title={e.message}>{e.message}</p>
                  </li>
                ))}
                {!summary.recent_errors.length && <li className="px-4 py-3 text-[13px] text-graphite">No errors in this window.</li>}
              </ul>
            </section>
          </div>

          <section className="flex flex-wrap items-center gap-3 text-[13px]">
            <span className="text-graphite">Backends:</span>
            {Object.entries(summary.links).map(([k, href]) => (
              <a key={k} href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded border border-rule px-2.5 py-1 hover:border-signal/50 hover:text-signal">
                {k} <Icon name="external" size={11} />
              </a>
            ))}
            <span className="ml-auto font-mono text-[11px] text-graphite">
              jira {summary.integrations.jira ? "on" : "off"} · git {summary.integrations.git ? "on" : "off"} · otlp {summary.integrations.otlp ? "on" : "off"} · vectors {summary.integrations.vectors ? "on" : "off"}
            </span>
          </section>
        </>
      )}
    </div>
  );
}
