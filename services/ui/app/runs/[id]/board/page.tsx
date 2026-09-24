"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type PlaneBoard } from "@/lib/api";
import Icon from "@/components/Icon";
import { GROUPS, GroupBar, PriorityMark } from "@/components/PlaneBits";

const GROUP_COLOR = Object.fromEntries(GROUPS.map((g) => [g.key, g.color]));

export default function BoardPage({ params }: { params: { id: string } }) {
  const runId = params.id;
  const [board, setBoard] = useState<PlaneBoard | null>(null);
  const [title, setTitle] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [module, setModule] = useState<string>("all");

  const refresh = useCallback(async () => {
    try {
      const [b, run] = await Promise.all([api.planeBoard(runId), api.getRun(runId).catch(() => null)]);
      setBoard(b);
      if (run) setTitle(run.title);
      setError(null);
    } catch (e: any) {
      setError(String(e?.message ?? e).slice(0, 300));
    } finally {
      setLoaded(true);
    }
  }, [runId]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => { void refresh(); }, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  async function sync() {
    setSyncing(true);
    try { await api.planeSync(runId); } catch (e: any) { setError(e.message); }
    setSyncing(false);
    void refresh();
  }

  const modules = useMemo(() => {
    const set = new Set<string>();
    board?.columns.forEach((c) => c.cards.forEach((k) => k.module && set.add(k.module)));
    return [...set].sort();
  }, [board]);

  const counts = useMemo(() => {
    const out = { backlog: 0, unstarted: 0, started: 0, completed: 0, cancelled: 0 } as Record<string, number>;
    board?.columns.forEach((c) => { out[c.group] = (out[c.group] ?? 0) + c.cards.length; });
    return out;
  }, [board]);

  if (!loaded) {
    return <div className="space-y-4" aria-busy><div className="skeleton h-10 w-1/3" /><div className="skeleton h-[520px]" /></div>;
  }

  const project = board?.project;
  const total = board?.total ?? 0;

  return (
    <div className="space-y-6">
      <div className="enter flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <Link href={`/runs/${runId}`} className="text-[12px] text-graphite hover:text-signal">← Back to the run</Link>
          <h1 className="mt-1 flex items-center gap-2.5 text-[28px] font-semibold tracking-[-0.02em]">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-signal text-white shadow-spectrum"><Icon name="board" size={18} /></span>
            {title || project?.name || "Board"}
          </h1>
          {project && (
            <p className="mt-1.5 text-[13px] text-graphite">
              Plane project <span className="font-mono text-ink">{project.identifier}</span> · {total} work item{total === 1 ? "" : "s"}
              {board?.sprint && <> · <a href={board.sprint.url} target="_blank" rel="noreferrer" className="text-signal hover:underline">{board.sprint.name ?? "Sprint 1"}</a></>}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {project && (
            <a href={project.url} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1.5 rounded-full bg-signal px-4 py-1.5 text-[13px] font-medium text-white shadow-spectrum hover:bg-[#0054B6]">
              Open in Plane <Icon name="external" size={12} />
            </a>
          )}
          <button onClick={sync} disabled={syncing || !board?.enabled}
                  className="inline-flex items-center gap-1.5 rounded-full border border-rule bg-paper px-4 py-1.5 text-[13px] hover:bg-mist disabled:opacity-50">
            {syncing && <span className="h-3 w-3 animate-spin rounded-full border-2 border-signal border-t-transparent" />}
            {project ? "Sync again" : "Mirror to Plane"}
          </button>
        </div>
      </div>

      {error && <p className="text-[13px] text-rust">{error}</p>}
      {board && !board.enabled && (
        <p className="rounded border border-ochre/30 bg-ochre/[0.06] px-3 py-2 text-[13px] text-ochre">
          Plane is not connected. Run <span className="font-mono">python scripts/plane-bootstrap.py</span> and restart the orchestrator.
        </p>
      )}

      {board && !project ? (
        <div className="enter rounded-xl border border-dashed border-rule bg-paper px-8 py-14 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#F5F9FF] text-signal"><Icon name="board" size={22} /></span>
          <p className="mt-3 text-[16px] font-semibold">This idea is not in Plane yet</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-[13px] text-graphite">
            New runs mirror themselves as soon as their backlog is approved. Press <b>Mirror to Plane</b> to bring this one in.
          </p>
        </div>
      ) : board && (
        <>
          <div className="enter flex flex-wrap items-center gap-4 rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum" style={{ animationDelay: "60ms" }}>
            <div className="min-w-[220px] flex-1"><GroupBar counts={counts as any} height={10} /></div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-graphite">
              {GROUPS.filter((g) => g.key !== "cancelled" || counts.cancelled).map((g) => (
                <span key={g.key} className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: g.color }} />{g.label} <b className="text-ink">{counts[g.key]}</b>
                </span>
              ))}
            </div>
            {modules.length > 0 && (
              <select value={module} onChange={(e) => setModule(e.target.value)}
                      className="rounded-full border border-rule bg-paper px-3 py-1 text-[12.5px]" aria-label="Filter by module">
                <option value="all">Every module</option>
                {modules.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            )}
          </div>

          <div className="enter -mx-1 overflow-x-auto pb-2" style={{ animationDelay: "120ms" }}>
            <div className="grid min-w-[980px] grid-cols-5 gap-3 px-1">
              {board.columns.map((col, ci) => {
                const cards = col.cards.filter((k) => module === "all" || k.module === module);
                const color = GROUP_COLOR[col.group] ?? "#8E8E8E";
                return (
                  <section key={col.id} className="flex min-h-[420px] flex-col rounded-xl border border-rule bg-mist/70">
                    <header className="flex items-center gap-2 border-b border-rule px-3 py-2.5">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
                      <h2 className="text-[13px] font-semibold">{col.name}</h2>
                      <span className="ml-auto rounded-full bg-paper px-2 font-mono text-[11px] text-graphite">{cards.length}</span>
                    </header>
                    <ul className="flex flex-1 flex-col gap-2 p-2">
                      {cards.map((k, i) => (
                        <li key={k.id} className="kanban-in" style={{ animationDelay: `${ci * 70 + i * 45}ms` }}>
                          <a href={k.url} target="_blank" rel="noreferrer"
                             className="group block rounded-lg border border-rule bg-paper p-3 shadow-spectrum transition hover:-translate-y-0.5 hover:border-signal/40 hover:shadow-md"
                             style={{ borderLeft: `3px solid ${color}` }}>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[11px] text-graphite">{k.key}</span>
                              <span className="ml-auto"><PriorityMark priority={k.priority} /></span>
                            </div>
                            <p className="mt-1 text-[13px] font-medium leading-snug group-hover:text-signal">{k.name}</p>
                            {k.module && <p className="mt-1 truncate text-[11.5px] text-graphite" title={k.module}>◇ {k.module}</p>}
                            {k.labels.filter((l) => l.name !== "poiesis").length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {k.labels.filter((l) => l.name !== "poiesis").map((l) => (
                                  <span key={l.name} className="rounded-full px-1.5 py-[1px] text-[10.5px] font-medium"
                                        style={{ color: l.color ?? "#6E6E6E", background: `${l.color ?? "#6E6E6E"}18` }}>{l.name}</span>
                                ))}
                              </div>
                            )}
                          </a>
                        </li>
                      ))}
                      {cards.length === 0 && <li className="grid flex-1 place-items-center text-[12px] text-graphite/70">Nothing here</li>}
                    </ul>
                  </section>
                );
              })}
            </div>
          </div>
          <p className="text-[12px] text-graphite">
            Cards open the work item in Plane. Sign in there as <span className="font-mono">admin@poiesis.local</span>; the password is in <span className="font-mono">infra/plane/plane.env</span>.
          </p>
        </>
      )}
    </div>
  );
}
