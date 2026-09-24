"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API, api, type Codemap, type CodemapJob, type CodemapModule } from "@/lib/api";
import Icon from "@/components/Icon";
import Mermaid from "@/components/Mermaid";

const KIND: Record<string, { label: string; color: string }> = {
  screen: { label: "Screen", color: "#0265DC" },
  api: { label: "Story API", color: "#4046CA" },
  generic: { label: "Generic data API", color: "#7E84FA" },
  model: { label: "Data model", color: "#0FB5AE" },
  db: { label: "Database", color: "#F68511" },
  shell: { label: "App shell", color: "#6D6D6D" },
  core: { label: "Service core", color: "#464646" },
};
const LANG_COLOR: Record<string, string> = {
  JavaScript: "#F68511", Python: "#4046CA", SQL: "#0FB5AE", CSS: "#DE3D82", HTML: "#7E84FA",
};

type Tab = "topology" | "modules" | "data" | "flows";

// `a -->|label| b`, `a -.->|label| b`, `a ==>|label| b` in the module view.
const EDGE = /^\s*(\w+)\s*(?:-\.->|==>|-->)\s*(?:\|[^|]*\|)?\s*(\w+)\s*$/;

function CountUp({ value }: { value: number }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 900);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{n.toLocaleString()}</>;
}

function Stat({ label, value, hint, delay }: { label: string; value: number; hint?: string; delay: number }) {
  return (
    <div className="enter rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum" style={{ animationDelay: `${delay}ms` }}>
      <p className="text-[12px] text-graphite">{label}</p>
      <p className="mt-0.5 text-[26px] font-semibold leading-none tracking-[-0.02em]"><CountUp value={value} /></p>
      {hint && <p className="mt-1 text-[11px] text-graphite">{hint}</p>}
    </div>
  );
}

function Languages({ langs }: { langs: Record<string, number> }) {
  const total = Object.values(langs).reduce((a, b) => a + b, 0) || 1;
  const list = Object.entries(langs).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-mist">
        {list.map(([l, n], i) => (
          <span key={l} className="bar-grow h-full" title={`${l} · ${n} lines`}
                style={{ width: `${(100 * n) / total}%`, background: LANG_COLOR[l] ?? "#8E8E8E", animationDelay: `${i * 90}ms` }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-graphite">
        {list.map(([l, n]) => (
          <span key={l} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: LANG_COLOR[l] ?? "#8E8E8E" }} />
            {l} <span className="font-mono text-[11px]">{Math.round((100 * n) / total)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Chip({ kind }: { kind: string }) {
  const k = KIND[kind] ?? { label: kind, color: "#6E6E6E" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
          style={{ borderColor: `${k.color}55`, color: k.color, background: `${k.color}10` }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: k.color }} />{k.label}
    </span>
  );
}

function Panel({ runId, mod, map, onFlow, onClose, onComponents }: {
  runId: string; mod: CodemapModule; map: Codemap; onFlow: (id: string) => void; onClose: () => void;
  onComponents: () => void;
}) {
  const classes = Array.from((mod.l2 ?? "").matchAll(/^\s*class (\w+) \{/gm)).map((m) => m[1]);
  const flows = map.flows.filter((f) => f.module === mod.id);
  return (
    <div key={mod.id} className="panel-in space-y-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Chip kind={mod.kind} />
          <h3 className="mt-1.5 text-[18px] font-semibold leading-tight">{mod.name}</h3>
          {mod.capability && <p className="mt-0.5 text-[12px] text-graphite">{mod.capability}</p>}
        </div>
        <button onClick={onClose} className="rounded-full p-1 text-graphite hover:bg-mist" aria-label="Close">
          <Icon name="x" size={14} />
        </button>
      </div>

      {mod.summary ? (
        <p className="rounded-lg border border-signal/20 bg-[#F5F9FF] px-3 py-2 text-[13px] leading-relaxed">
          <span className="mb-0.5 flex items-center gap-1 text-[11px] font-medium text-signal"><Icon name="spark" size={11} /> {mod.responsibility || "Summary"}</span>
          {mod.summary}
        </p>
      ) : mod.subtitle ? (
        <p className="text-[13px] text-graphite">{mod.subtitle}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-2 text-[12px]">
        <div className="rounded border border-rule px-2.5 py-1.5"><p className="text-graphite">Lines of code</p><p className="font-mono text-[14px]">{mod.loc}</p></div>
        <div className="rounded border border-rule px-2.5 py-1.5"><p className="text-graphite">Files</p><p className="font-mono text-[14px]">{mod.files.length}</p></div>
      </div>

      {mod.calls && mod.calls.length > 0 && (
        <section>
          <p className="mb-1 text-[12px] font-medium text-graphite">Calls</p>
          <ul className="space-y-1 font-mono text-[11.5px]">
            {mod.calls.map((c, i) => (
              <li key={i} className={`flex gap-2 rounded px-2 py-1 ${c.route ? "bg-mist" : "bg-rust/10 text-rust"}`}>
                <span className="w-[46px] shrink-0 font-semibold">{c.method}</span>
                <span className="truncate" title={c.path}>{c.route ?? c.path}</span>
                {!c.route && <span className="ml-auto shrink-0">not served</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {mod.endpoints && mod.endpoints.length > 0 && (
        <section>
          <p className="mb-1 text-[12px] font-medium text-graphite">Serves</p>
          <ul className="space-y-1 font-mono text-[11.5px]">
            {mod.endpoints.map((e) => {
              const [m, ...p] = e.split(" ");
              return (
                <li key={e} className="flex gap-2 rounded bg-mist px-2 py-1">
                  <span className="w-[46px] shrink-0 font-semibold text-[#4046CA]">{m.length > 6 ? "CRUD" : m}</span>
                  <span className="truncate" title={e}>{p.join(" ")}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {mod.tables && (
        <section>
          <p className="mb-1 text-[12px] font-medium text-graphite">Tables</p>
          <div className="flex flex-wrap gap-1.5">
            {mod.tables.map((t) => <span key={t} className="rounded-full border border-rule px-2 py-0.5 font-mono text-[11px]">{t}</span>)}
          </div>
        </section>
      )}

      {flows.length > 0 && (
        <section>
          <p className="mb-1 text-[12px] font-medium text-graphite">Request flows</p>
          <ul className="space-y-1">
            {flows.map((f) => (
              <li key={f.id}>
                <button onClick={() => onFlow(f.id)} className="w-full rounded border border-rule px-2.5 py-1.5 text-left text-[12.5px] hover:border-signal hover:bg-[#F5F9FF]">
                  {f.name}<span className="block font-mono text-[11px] text-graphite">{f.trigger}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mod.l2 && (
        <section>
          <div className="mb-1 flex items-center">
            <p className="text-[12px] font-medium text-graphite">Components (ArchiLens L2)</p>
            <button onClick={onComponents} className="ml-auto text-[12px] font-medium text-signal hover:underline">Show diagram →</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {classes.map((c) => <span key={c} className="rounded border border-rule bg-mist px-1.5 py-0.5 font-mono text-[11px]">{c}</span>)}
          </div>
        </section>
      )}

      <section>
        <p className="mb-1 text-[12px] font-medium text-graphite">Source</p>
        <ul className="space-y-0.5 font-mono text-[11.5px]">
          {mod.files.map((f) => (
            <li key={f}>
              <a href={`${API}/api/runs/${runId}/file?path=${encodeURIComponent(f)}`} target="_blank" rel="noreferrer"
                 className="text-signal hover:underline">{f}</a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function CodebasePage({ params }: { params: { id: string } }) {
  const runId = params.id;
  const [map, setMap] = useState<Codemap | null>(null);
  const [job, setJob] = useState<CodemapJob>({ running: false });
  const [available, setAvailable] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<Tab>("modules");
  const [picked, setPicked] = useState<string | null>(null);
  const [flowId, setFlowId] = useState<string | null>(null);
  const [l2Of, setL2Of] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.codemap(runId);
      setMap(r.map);
      setJob(r.job);
      setAvailable(r.available);
      setError(null);
    } catch {
      setError("The orchestrator is not answering on port 8080.");
    } finally {
      setLoaded(true);
    }
  }, [runId]);

  useEffect(() => { void refresh(); }, [refresh]);
  const working = job.running || map?.ai?.status === "running";
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => { void refresh(); }, 4000);
    return () => clearInterval(t);
  }, [working, refresh]);

  async function draw(ai: boolean) {
    try {
      await api.drawCodemap(runId, ai);
      setJob({ running: true, stage: "reading the code" });
      setTimeout(() => { void refresh(); }, 1500);
    } catch (e: any) {
      setError(e.message ?? "That did not work.");
    }
  }

  const byMid = useMemo(() => new Map((map?.modules ?? []).map((m) => [m.mid, m])), [map]);
  const neighbours = useMemo(() => {
    if (!map || !picked) return null;
    const lit = new Set<string>([picked]);
    for (const line of map.views.modules.split("\n")) {
      const m = EDGE.exec(line);
      if (m && (m[1] === picked || m[2] === picked)) { lit.add(m[1]); lit.add(m[2]); }
    }
    return lit;
  }, [map, picked]);

  const selected = picked ? byMid.get(picked) ?? null : null;
  const flow = map?.flows.find((f) => f.id === flowId) ?? map?.flows[0] ?? null;

  if (!loaded) {
    return <div className="space-y-4" aria-busy><div className="skeleton h-10 w-1/3" /><div className="skeleton h-24" /><div className="skeleton h-[520px]" /></div>;
  }

  const tabs: { key: Tab; label: string; count?: number; show: boolean }[] = [
    { key: "topology", label: "Runtime topology", show: !!map?.views.topology },
    { key: "modules", label: "Modules & stories", count: map?.modules.length, show: !!map },
    { key: "data", label: "Data model", count: map?.stats.tables, show: !!map?.views.data },
    { key: "flows", label: "Request flows", count: map?.flows.length, show: !!map },
  ];

  return (
    <div className="space-y-6">
      <div className="enter flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <Link href={`/runs/${runId}`} className="text-[12px] text-graphite hover:text-signal">← Back to the run</Link>
          <h1 className="mt-1 flex items-center gap-2.5 text-[28px] font-semibold tracking-[-0.02em]">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-signal text-white shadow-spectrum"><Icon name="map" size={18} /></span>
            {map?.title ?? "Codebase"}
          </h1>
          {map && (
            <p className="mt-1.5 text-[13px] text-graphite">
              Drawn by <a href="https://github.com/saurabh-oss/archilens" target="_blank" rel="noreferrer" className="text-signal hover:underline">{map.engine}</a>
              {map.git_ref && <> from <span className="font-mono">{map.git_ref}</span></>} · {new Date(map.generated_at).toLocaleString()}
              {map.ai?.status === "done" && <> · explained by <span className="font-mono">{map.ai.model}</span> (local)</>}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {working && (
            <span className="inline-flex items-center gap-2 rounded-full border border-signal/30 bg-[#F5F9FF] px-3 py-1.5 text-[12px] text-signal">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-signal border-t-transparent" />
              {job.stage || "working"}
            </span>
          )}
          {map && (
            <a href={`${API}/api/runs/${runId}/codemap/snapshot`} target="_blank" rel="noreferrer"
               className="rounded-full border border-rule bg-paper px-3.5 py-1.5 text-[13px] hover:bg-mist">ArchiLens snapshot</a>
          )}
          <button disabled={working || !available} onClick={() => draw(false)}
                  className="rounded-full border border-rule bg-paper px-3.5 py-1.5 text-[13px] hover:bg-mist disabled:opacity-50">
            {map ? "Redraw" : "Draw map"}
          </button>
          <button disabled={working || !available} onClick={() => draw(true)}
                  className="inline-flex items-center gap-1.5 rounded-full bg-signal px-4 py-1.5 text-[13px] font-medium text-white shadow-spectrum hover:bg-[#0054B6] disabled:opacity-50">
            <Icon name="spark" size={13} /> {map?.ai?.status === "done" ? "Explain again" : "Explain with local AI"}
          </button>
        </div>
      </div>

      {error && <p className="text-[13px] text-rust">{error}</p>}
      {job.error && <p className="rounded border border-rust/30 bg-rust/5 px-3 py-2 text-[13px] text-rust">The last drawing failed: {job.error}</p>}
      {map?.ai?.status === "failed" && <p className="text-[13px] text-rust">The local model could not finish: {map.ai.error}</p>}
      {!available && <p className="text-[13px] text-rust">ArchiLens is not installed in the orchestrator image; rebuild it.</p>}

      {!map ? (
        <div className="enter rounded-xl border border-dashed border-rule bg-paper px-8 py-14 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#F5F9FF] text-signal"><Icon name="map" size={22} /></span>
          <p className="mt-3 text-[16px] font-semibold">No map of this codebase yet</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-[13px] text-graphite">
            ArchiLens reads the code and draws its topology, modules, data model and request flows.
            New runs are drawn automatically after every deploy.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            <Stat label="Lines of code" value={map.stats.loc} delay={0} />
            <Stat label="Files" value={map.stats.files} delay={40} />
            <Stat label="Modules" value={map.stats.modules} delay={80} />
            <Stat label="Screens" value={map.stats.screens} delay={120} />
            <Stat label="Story endpoints" value={map.stats.story_endpoints} hint={`${map.stats.endpoints} with generic`} delay={160} />
            <Stat label="Tables" value={map.stats.tables} delay={200} />
            <Stat label="Request flows" value={map.flows.length} hint={map.ai?.status === "done" ? "traced locally" : "explain to trace"} delay={240} />
          </div>

          <div className="enter grid gap-4 rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum md:grid-cols-[minmax(0,1fr)_auto]" style={{ animationDelay: "280ms" }}>
            <Languages langs={map.stats.languages} />
            <div className="flex flex-wrap items-center gap-1.5">
              {map.patterns.length > 0 ? map.patterns.map((p) => (
                <span key={p} className="rounded-full bg-[#F5F9FF] px-2.5 py-1 text-[12px] font-medium capitalize text-signal">{p.replace(/_/g, " ")}</span>
              )) : <span className="text-[12px] text-graphite">Patterns appear once the local model has explained the code.</span>}
              {(map.stats.unserved_calls ?? 0) > 0 && (
                <span className="rounded-full bg-rust/10 px-2.5 py-1 text-[12px] font-medium text-rust">{map.stats.unserved_calls} call(s) to endpoints nobody serves</span>
              )}
            </div>
          </div>

          <div className="enter flex flex-wrap items-center gap-2" style={{ animationDelay: "320ms" }}>
          <div className="flex flex-wrap gap-1 rounded-full border border-rule bg-mist p-1 text-[13px]">
            {tabs.filter((t) => t.show).map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                      className={`rounded-full px-3.5 py-1.5 transition ${tab === t.key ? "bg-paper font-medium text-ink shadow-spectrum" : "text-graphite hover:text-ink"}`}>
                {t.label}{t.count !== undefined && <span className="ml-1.5 font-mono text-[11px] text-graphite">{t.count}</span>}
              </button>
            ))}
          </div>
            {tab === "modules" && (
              <div className="ml-2 flex flex-wrap items-center gap-1.5 self-center">
                {["screen", "api", "generic", "model", "db", "shell", "core"].map((k) => <Chip key={k} kind={k} />)}
              </div>
            )}
          </div>

          <div className="enter grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]" style={{ animationDelay: "360ms" }}>
            <div className="canvas-grid relative rounded-xl border border-rule shadow-spectrum">
              {tab === "topology" && <Mermaid code={map.views.topology} minHeight={560} />}
              {tab === "modules" && l2Of && byMid.get(l2Of)?.l2 ? (
                <div>
                  <div className="flex items-center gap-2 border-b border-rule bg-paper/80 px-4 py-2.5 backdrop-blur">
                    <p className="text-[14px] font-semibold">{byMid.get(l2Of)!.name}</p>
                    <span className="text-[12px] text-graphite">components · ArchiLens L2</span>
                    <button onClick={() => setL2Of(null)} className="ml-auto rounded-full border border-rule px-3 py-1 text-[12px] hover:bg-mist">← All modules</button>
                  </div>
                  <Mermaid key={l2Of} code={byMid.get(l2Of)!.l2!} minHeight={574} />
                </div>
              ) : tab === "modules" && (
                <Mermaid code={map.views.modules} minHeight={620} selected={picked} lit={neighbours}
                         onNode={(id) => { setPicked(id === picked ? null : id); }} />
              )}
              {tab === "data" && <Mermaid code={map.views.data} minHeight={620} />}
              {tab === "flows" && (flow ? (
                <div>
                  <div className="border-b border-rule bg-paper/80 px-4 py-2.5 backdrop-blur">
                    <p className="text-[15px] font-semibold">{flow.name}</p>
                    <p className="font-mono text-[12px] text-graphite">{flow.trigger}</p>
                    {flow.description && <p className="mt-0.5 text-[12.5px] text-graphite">{flow.description}</p>}
                  </div>
                  <Mermaid key={flow.id} code={flow.mermaid} minHeight={560} />
                </div>
              ) : (
                <div className="grid min-h-[420px] place-items-center px-8 text-center">
                  <div>
                    <p className="text-[15px] font-semibold">No request flows yet</p>
                    <p className="mx-auto mt-1 max-w-[46ch] text-[13px] text-graphite">
                      ArchiLens traces each story endpoint from the request to the database. It needs a
                      model for that; press <b>Explain with local AI</b> — it runs on the local model, one call at a time.
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <aside className="rounded-xl border border-rule bg-paper p-4 shadow-spectrum lg:max-h-[640px] lg:overflow-y-auto">
              {tab === "flows" ? (
                <div className="space-y-1.5">
                  <p className="mb-2 text-[12px] font-medium text-graphite">Flows traced by ArchiLens</p>
                  {map.flows.length === 0 && <p className="text-[13px] text-graphite">None yet.</p>}
                  {map.flows.map((f) => (
                    <button key={f.id} onClick={() => setFlowId(f.id)}
                            className={`w-full rounded-lg border px-3 py-2 text-left text-[13px] transition ${flow?.id === f.id ? "border-signal bg-[#F5F9FF]" : "border-rule hover:border-signal/50"}`}>
                      <span className="font-medium">{f.name}</span>
                      <span className="block font-mono text-[11px] text-graphite">{f.trigger} · {f.steps} steps</span>
                    </button>
                  ))}
                </div>
              ) : tab === "modules" && selected ? (
                <Panel runId={runId} mod={selected} map={map} onClose={() => { setPicked(null); setL2Of(null); }}
                       onComponents={() => setL2Of(selected.mid)}
                       onFlow={(id) => { setFlowId(id); setTab("flows"); }} />
              ) : tab === "modules" ? (
                <div className="space-y-3">
                  <p className="text-[13px] text-graphite">Click any box to see what it is, what it calls and what it serves. Drag to pan, scroll to zoom.</p>
                  <p className="text-[12px] font-medium text-graphite">Stories</p>
                  <ul className="space-y-1">
                    {Object.entries(map.capabilities).map(([cap, ids]) => (
                      <li key={cap}>
                        <button onClick={() => setPicked(map.modules.find((m) => m.id === ids[0])?.mid ?? null)}
                                className="w-full rounded-lg border border-rule px-3 py-1.5 text-left text-[12.5px] hover:border-signal hover:bg-[#F5F9FF]">
                          <span className="font-mono text-[11px] text-signal">{cap.split(" ")[0]}</span> {cap.split(" ").slice(1).join(" ")}
                          <span className="float-right font-mono text-[11px] text-graphite">{ids.length}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : tab === "topology" ? (
                <div className="space-y-2 text-[13px] text-graphite">
                  <p className="font-medium text-ink">The standard topology</p>
                  <p>Every Poiesis app runs the same four services. The gateway serves the screens and sends <span className="font-mono">/api</span> to the api service; when a story module breaks it, the data service keeps every screen showing data.</p>
                  <p>Read from <span className="font-mono">docker-compose.yml</span> and the gateway&apos;s <span className="font-mono">nginx.conf</span>.</p>
                </div>
              ) : (
                <div className="space-y-2 text-[13px] text-graphite">
                  <p className="font-medium text-ink">Data model</p>
                  <p>Tables and columns from <span className="font-mono">db/init.sql</span>. Solid lines are declared foreign keys; dashed lines are <span className="font-mono">*_id</span> columns that name another table.</p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {(map.modules.find((m) => m.kind === "db")?.tables ?? []).map((t) => (
                      <span key={t} className="rounded-full border border-rule px-2 py-0.5 font-mono text-[11px]">{t}</span>
                    ))}
                  </div>
                </div>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
