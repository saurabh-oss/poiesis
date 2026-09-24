"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type PlaneBoard } from "@/lib/api";
import Icon from "./Icon";
import { GROUPS, GroupBar } from "./PlaneBits";

/** The run's Plane board at a glance, with a way into the full board and into Plane. */
export default function BoardCard({ runId, active }: { runId: string; active: boolean }) {
  const [board, setBoard] = useState<PlaneBoard | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.planeBoard(runId).then((b) => { if (alive) setBoard(b); }).catch(() => {});
    void load();
    const t = setInterval(load, active ? 10000 : 30000);
    return () => { alive = false; clearInterval(t); };
  }, [runId, active]);

  if (!board?.enabled) return null;
  const counts = { backlog: 0, unstarted: 0, started: 0, completed: 0, cancelled: 0 } as Record<string, number>;
  board.columns.forEach((c) => { counts[c.group] = (counts[c.group] ?? 0) + c.cards.length; });

  return (
    <div className="overflow-hidden rounded border border-rule bg-paper shadow-spectrum">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <Icon name="board" size={14} className="text-signal" />
        <p className="text-[13px] font-medium">Board</p>
        <span className="ml-auto font-mono text-[11px] text-graphite">{board.project ? `Plane · ${board.project.identifier}` : "Plane"}</span>
      </div>
      {board.project ? (
        <div className="space-y-2.5 border-t border-rule px-4 py-3">
          <GroupBar counts={counts as any} />
          <div className="grid grid-cols-4 gap-1 text-center">
            {GROUPS.slice(0, 4).map((g) => (
              <div key={g.key}>
                <p className="text-[14px] font-semibold leading-none" style={{ color: counts[g.key] ? g.color : undefined }}>{counts[g.key]}</p>
                <p className="mt-0.5 text-[10.5px] text-graphite">{g.label}</p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="border-t border-rule px-4 py-3 text-[12.5px] text-graphite">
          The project appears here as soon as the backlog is approved.
        </p>
      )}
      <div className="flex items-center gap-3 border-t border-rule px-4 py-2.5">
        {board.project && (
          <a href={board.project.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12px] text-graphite hover:text-signal">
            Plane <Icon name="external" size={11} />
          </a>
        )}
        <Link href={`/runs/${runId}/board`} className="ml-auto text-[13px] font-medium text-signal hover:underline">Open board →</Link>
      </div>
    </div>
  );
}
