"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type CodebaseRow } from "@/lib/api";
import Icon from "@/components/Icon";
import Mermaid from "@/components/Mermaid";

const LANG_COLOR: Record<string, string> = {
  JavaScript: "#F68511", Python: "#4046CA", SQL: "#0FB5AE", CSS: "#DE3D82", HTML: "#7E84FA",
};

function LangBar({ langs }: { langs: Record<string, number> }) {
  const total = Object.values(langs).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="flex h-1.5 overflow-hidden rounded-full bg-mist">
      {Object.entries(langs).sort((a, b) => b[1] - a[1]).map(([l, n], i) => (
        <span key={l} title={`${l} · ${n} lines`} className="bar-grow h-full"
              style={{ width: `${(100 * n) / total}%`, background: LANG_COLOR[l] ?? "#8E8E8E", animationDelay: `${200 + i * 80}ms` }} />
      ))}
    </div>
  );
}

function Card({ row, index, onDraw }: { row: CodebaseRow; index: number; onDraw: (id: string) => void }) {
  const s = row.stats;
  const busy = row.job?.running || row.ai?.status === "running";
  return (
    <article className="enter spot group relative flex flex-col overflow-hidden rounded-xl border border-rule bg-paper shadow-spectrum transition hover:-translate-y-0.5 hover:shadow-lg"
             style={{ animationDelay: `${Math.min(index * 60, 600)}ms` }}>
      <div className="canvas-grid relative h-[178px] border-b border-rule">
        {row.analysed && row.preview ? (
          <Mermaid code={row.preview} interactive={false} minHeight={178} />
        ) : (
          <div className="grid h-full place-items-center text-graphite">
            <div className="text-center">
              <Icon name="map" size={26} className="mx-auto opacity-50" />
              <p className="mt-1 text-[12px]">{busy ? row.job?.stage || "drawing…" : "Not drawn yet"}</p>
            </div>
          </div>
        )}
        {busy && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-full bg-paper/90 px-2 py-0.5 text-[11px] text-signal shadow-spectrum">
            <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-signal border-t-transparent" /> {row.job?.stage || "explaining"}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h2 className="truncate text-[16px] font-semibold" title={row.title}>{row.title}</h2>
          <p className="font-mono text-[11px] text-graphite">
            {row.run_id}{row.git_ref ? ` · ${row.git_ref}` : ""} · {row.status}
          </p>
        </div>
        {s ? (
          <>
            <div className="grid grid-cols-4 gap-2 text-center">
              {[["LOC", s.loc], ["Screens", s.screens], ["APIs", s.story_endpoints], ["Tables", s.tables]].map(([l, v]) => (
                <div key={l as string} className="rounded-lg bg-mist px-1 py-1.5">
                  <p className="text-[15px] font-semibold leading-none">{(v as number).toLocaleString()}</p>
                  <p className="mt-0.5 text-[10.5px] text-graphite">{l}</p>
                </div>
              ))}
            </div>
            <LangBar langs={s.languages} />
            <div className="flex flex-wrap gap-1">
              {row.ai?.status === "done" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-[#F5F9FF] px-2 py-0.5 text-[11px] text-signal">
                  <Icon name="spark" size={10} /> {row.flows} flows traced
                </span>
              )}
              {(row.patterns ?? []).slice(0, 3).map((p) => (
                <span key={p} className="rounded-full border border-rule px-2 py-0.5 text-[11px] capitalize text-graphite">{p.replace(/_/g, " ")}</span>
              ))}
              {(s.unserved_calls ?? 0) > 0 && (
                <span className="rounded-full bg-rust/10 px-2 py-0.5 text-[11px] text-rust">{s.unserved_calls} unserved call(s)</span>
              )}
            </div>
          </>
        ) : (
          <p className="text-[13px] text-graphite">ArchiLens has not read this codebase yet.</p>
        )}
        <div className="mt-auto flex gap-2 pt-1">
          {row.analysed ? (
            <Link href={`/runs/${row.run_id}/codebase`}
                  className="inline-flex items-center gap-1.5 rounded-full bg-signal px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-[#0054B6]">
              <Icon name="map" size={13} /> Open map
            </Link>
          ) : (
            <button onClick={() => onDraw(row.run_id)} disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-full bg-signal px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-[#0054B6] disabled:opacity-50">
              <Icon name="map" size={13} /> Draw map
            </button>
          )}
          <Link href={`/runs/${row.run_id}`} className="rounded-full border border-rule px-3.5 py-1.5 text-[13px] hover:bg-mist">Run</Link>
        </div>
      </div>
    </article>
  );
}

export default function CodebasesPage() {
  const [rows, setRows] = useState<CodebaseRow[]>([]);
  const [available, setAvailable] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.codebases();
      setRows(r.codebases);
      setAvailable(r.available);
      setError(null);
    } catch {
      setError("The orchestrator is not answering on port 8080.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  const busy = rows.some((r) => r.job?.running || r.ai?.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { void refresh(); }, 5000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  async function draw(id: string, ai = false) {
    try {
      await api.drawCodemap(id, ai);
      setTimeout(() => { void refresh(); }, 1200);
    } catch (e: any) {
      setError(e.message ?? "That did not work.");
    }
  }

  async function drawAll() {
    for (const r of rows.filter((x) => !x.analysed)) await draw(r.run_id);
  }

  const drawn = rows.filter((r) => r.analysed);
  const loc = drawn.reduce((a, r) => a + (r.stats?.loc ?? 0), 0);
  const screens = drawn.reduce((a, r) => a + (r.stats?.screens ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="enter flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Codebases</h1>
          <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-graphite">
            Every application Poiesis has generated, drawn by{" "}
            <a href="https://github.com/saurabh-oss/archilens" target="_blank" rel="noreferrer" className="text-signal hover:underline">ArchiLens</a>:
            runtime topology, modules grouped by story, the data model and request flows. Maps redraw after every deploy;
            the explanations come from the local model once a run goes idle.
          </p>
        </div>
        {rows.some((r) => !r.analysed) && (
          <button onClick={drawAll} disabled={!available}
                  className="inline-flex items-center gap-1.5 rounded-full bg-signal px-4 py-2 text-[13px] font-medium text-white shadow-spectrum hover:bg-[#0054B6] disabled:opacity-50">
            <Icon name="map" size={14} /> Draw every map
          </button>
        )}
      </div>

      {loaded && drawn.length > 0 && (
        <div className="enter grid grid-cols-3 gap-3 sm:max-w-[560px]" style={{ animationDelay: "80ms" }}>
          {[["Codebases", rows.length], ["Lines drawn", loc], ["Screens", screens]].map(([l, v]) => (
            <div key={l as string} className="rounded-lg border border-rule bg-paper px-4 py-3 shadow-spectrum">
              <p className="text-[12px] text-graphite">{l}</p>
              <p className="text-[24px] font-semibold leading-tight">{(v as number).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}

      {error && <p className="text-[13px] text-rust">{error}</p>}
      {!available && <p className="text-[13px] text-rust">ArchiLens is not installed in the orchestrator image; rebuild it.</p>}

      {!loaded ? (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton h-[380px] rounded-xl" />)}
        </div>
      ) : rows.length === 0 ? (
        <p className="text-[14px] text-graphite">No run has produced a codebase yet.</p>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((r, i) => <Card key={r.run_id} row={r} index={i} onDraw={(id) => draw(id)} />)}
        </div>
      )}
    </div>
  );
}
