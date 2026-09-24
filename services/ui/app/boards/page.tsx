"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type PlaneIdea } from "@/lib/api";
import Icon from "@/components/Icon";
import { GROUPS, GroupBar } from "@/components/PlaneBits";

function IdeaCard({ idea, index, onSync, busy }: { idea: PlaneIdea; index: number; onSync: (id: string) => void; busy: boolean }) {
  const c = idea.counts;
  const total = c ? GROUPS.reduce((a, g) => a + c[g.key], 0) : 0;
  const done = c?.completed ?? 0;
  return (
    <article className="enter group relative flex flex-col overflow-hidden rounded-xl border border-rule bg-paper shadow-spectrum transition hover:-translate-y-0.5 hover:shadow-lg"
             style={{ animationDelay: `${Math.min(index * 50, 600)}ms` }}>
      <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-[#0265DC] via-[#5258E4] to-[#EB1000] opacity-0 transition group-hover:opacity-100" />
      <div className="flex items-start gap-3 p-4 pb-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[#F5F9FF] font-mono text-[11px] font-semibold text-signal">
          {(idea.project?.identifier ?? idea.title).slice(0, 3).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15.5px] font-semibold" title={idea.title}>{idea.title}</h2>
          <p className="font-mono text-[11px] text-graphite">
            {idea.project ? idea.project.identifier : "not in Plane yet"} · {idea.run_id.slice(0, 8)} · {idea.status}
          </p>
        </div>
        {c && total > 0 && (
          <span className="shrink-0 text-right">
            <span className="block text-[18px] font-semibold leading-none">{Math.round((100 * done) / total)}%</span>
            <span className="text-[10.5px] text-graphite">done</span>
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-3 px-4 pb-4">
        {c ? (
          <>
            <GroupBar counts={c} />
            <div className="grid grid-cols-4 gap-1.5 text-center">
              {GROUPS.slice(0, 4).map((g) => (
                <div key={g.key} className="rounded-md bg-mist px-1 py-1.5">
                  <p className="text-[15px] font-semibold leading-none" style={{ color: c[g.key] ? g.color : undefined }}>{c[g.key]}</p>
                  <p className="mt-0.5 text-[10.5px] text-graphite">{g.label}</p>
                </div>
              ))}
            </div>
            <p className="text-[12px] text-graphite">
              {idea.epics} module{idea.epics === 1 ? "" : "s"} · {idea.stories} stor{idea.stories === 1 ? "y" : "ies"}
              {idea.sprint && <> · {idea.sprint.name ?? "Sprint 1"}</>}
              {idea.release && <> · release item</>}
            </p>
          </>
        ) : (
          <p className="text-[13px] text-graphite">{idea.project ? "Plane did not answer for this project." : "This idea's backlog has not been mirrored yet."}</p>
        )}
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          {idea.project ? (
            <>
              <Link href={`/runs/${idea.run_id}/board`}
                    className="inline-flex items-center gap-1.5 rounded-full bg-signal px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-[#0054B6]">
                <Icon name="board" size={13} /> Board
              </Link>
              <a href={idea.project.url} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1.5 rounded-full border border-rule px-3.5 py-1.5 text-[13px] hover:bg-mist">
                Open in Plane <Icon name="external" size={12} />
              </a>
            </>
          ) : (
            <button onClick={() => onSync(idea.run_id)} disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-full bg-signal px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-[#0054B6] disabled:opacity-50">
              <Icon name="upload" size={13} /> Mirror to Plane
            </button>
          )}
          <Link href={`/runs/${idea.run_id}`} className="rounded-full border border-rule px-3.5 py-1.5 text-[13px] hover:bg-mist">Run</Link>
        </div>
      </div>
    </article>
  );
}

export default function BoardsPage() {
  const [ideas, setIdeas] = useState<PlaneIdea[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [url, setUrl] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.planeOverview();
      setIdeas(r.ideas);
      setEnabled(r.enabled);
      setUrl(r.url);
      setSyncing(r.syncing);
      setError(null);
    } catch {
      setError("The orchestrator is not answering on port 8080.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!syncing && !busy) return;
    const t = setInterval(() => { void refresh(); }, 4000);
    return () => clearInterval(t);
  }, [syncing, busy, refresh]);

  async function sync(id: string) {
    setBusy(id);
    try { await api.planeSync(id); } catch (e: any) { setError(e.message); }
    setBusy(null);
    void refresh();
  }

  async function syncAll() {
    try { await api.planeSyncAll(); setSyncing(true); } catch (e: any) { setError(e.message); }
  }

  const mirrored = ideas.filter((i) => i.project);
  const totals = mirrored.reduce((a, i) => {
    if (i.counts) GROUPS.forEach((g) => { a[g.key] = (a[g.key] ?? 0) + i.counts![g.key]; });
    return a;
  }, {} as Record<string, number>);
  const items = Object.values(totals).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <div className="enter flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Boards</h1>
          <p className="mt-2 max-w-[72ch] text-[15px] leading-relaxed text-graphite">
            Every idea gets its own project in <a href={url || "#"} target="_blank" rel="noreferrer" className="text-signal hover:underline">Plane</a>,
            the open-source tracker running on this machine. Its epics become modules, its stories become work items,
            and its first sprint becomes a cycle. Cards move across the board as the agents build, pass or fail each story.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {url && (
            <a href={url} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1.5 rounded-full border border-rule bg-paper px-4 py-2 text-[13px] hover:bg-mist">
              Open Plane <Icon name="external" size={12} />
            </a>
          )}
          {ideas.some((i) => !i.project) && (
            <button onClick={syncAll} disabled={!enabled || syncing}
                    className="inline-flex items-center gap-1.5 rounded-full bg-signal px-4 py-2 text-[13px] font-medium text-white shadow-spectrum hover:bg-[#0054B6] disabled:opacity-50">
              {syncing ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" /> : <Icon name="upload" size={13} />}
              {syncing ? "Mirroring…" : "Mirror every idea"}
            </button>
          )}
        </div>
      </div>

      {!enabled && (
        <p className="rounded border border-ochre/30 bg-ochre/[0.06] px-3 py-2 text-[13px] text-ochre">
          Plane is not connected. Start it and run <span className="font-mono">python scripts/plane-bootstrap.py</span>, then restart the orchestrator.
        </p>
      )}
      {error && <p className="text-[13px] text-rust">{error}</p>}

      {loaded && mirrored.length > 0 && (
        <div className="enter grid gap-3 sm:grid-cols-[repeat(3,minmax(0,160px))_minmax(0,1fr)]" style={{ animationDelay: "80ms" }}>
          {[["Ideas in Plane", mirrored.length], ["Work items", items], ["Done", totals.completed ?? 0]].map(([l, v]) => (
            <div key={l as string} className="rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum">
              <p className="text-[12px] text-graphite">{l}</p>
              <p className="text-[24px] font-semibold leading-tight">{(v as number).toLocaleString()}</p>
            </div>
          ))}
          <div className="rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum">
            <p className="mb-2 text-[12px] text-graphite">Across every board</p>
            {items > 0 && <GroupBar counts={totals as any} height={10} />}
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-graphite">
              {GROUPS.map((g) => (
                <span key={g.key} className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: g.color }} />{g.label} {totals[g.key] ?? 0}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {!loaded ? (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton h-[240px] rounded-xl" />)}
        </div>
      ) : ideas.length === 0 ? (
        <p className="text-[14px] text-graphite">No idea has an approved backlog yet.</p>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {ideas.map((i, n) => <IdeaCard key={i.run_id} idea={i} index={n} onSync={sync} busy={busy !== null || syncing} />)}
        </div>
      )}
    </div>
  );
}
