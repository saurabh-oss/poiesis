"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Codemap, type CodemapJob } from "@/lib/api";
import Icon from "./Icon";
import Mermaid from "./Mermaid";

/** The run's codebase at a glance, drawn by ArchiLens, with a way into the full map. */
export default function CodemapCard({ runId }: { runId: string }) {
  const [map, setMap] = useState<Codemap | null>(null);
  const [job, setJob] = useState<CodemapJob>({ running: false });

  useEffect(() => {
    let alive = true;
    const load = () => api.codemap(runId).then((r) => { if (alive) { setMap(r.map); setJob(r.job); } }).catch(() => {});
    void load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [runId]);

  const busy = job.running || map?.ai?.status === "running";
  return (
    <div className="overflow-hidden rounded border border-rule bg-paper shadow-spectrum">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <Icon name="map" size={14} className="text-signal" />
        <p className="text-[13px] font-medium">Codebase map</p>
        <span className="ml-auto text-[11px] text-graphite">ArchiLens</span>
      </div>
      {map ? (
        <>
          <div className="canvas-grid border-y border-rule">
            <Mermaid code={map.views.topology} interactive={false} minHeight={150} />
          </div>
          <div className="grid grid-cols-4 gap-1 px-3 py-2.5 text-center">
            {[["LOC", map.stats.loc], ["Screens", map.stats.screens], ["APIs", map.stats.story_endpoints], ["Tables", map.stats.tables]].map(([l, v]) => (
              <div key={l as string}>
                <p className="text-[14px] font-semibold leading-none">{(v as number).toLocaleString()}</p>
                <p className="mt-0.5 text-[10.5px] text-graphite">{l}</p>
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className="border-t border-rule px-4 py-3 text-[12.5px] text-graphite">
          {busy ? `Drawing: ${job.stage ?? "reading the code"}…` : "Drawn automatically after the application is deployed."}
        </p>
      )}
      <div className="flex items-center gap-2 border-t border-rule px-4 py-2.5">
        {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-signal border-t-transparent" />}
        <span className="text-[11.5px] text-graphite">
          {map?.ai?.status === "done" ? `${map.flows.length} flows traced locally` : busy ? job.stage ?? "working" : ""}
        </span>
        <Link href={`/runs/${runId}/codebase`} className="ml-auto text-[13px] font-medium text-signal hover:underline">
          Open map →
        </Link>
      </div>
    </div>
  );
}
