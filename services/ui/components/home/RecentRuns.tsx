"use client";

import Link from "next/link";
import type { RunSummary, Stage } from "@/lib/api";
import { ago } from "@/lib/progress";
import Icon from "../Icon";

const TONE: Record<string, { bar: string; pill: string; label: string }> = {
  running: { bar: "bg-signal", pill: "border-signal/40 bg-signal/[0.06] text-signal", label: "working" },
  waiting: { bar: "bg-ochre", pill: "border-ochre/50 bg-ochre/[0.07] text-ochre", label: "needs you" },
  complete: { bar: "bg-moss", pill: "border-moss/40 bg-moss/[0.06] text-moss", label: "complete" },
  released: { bar: "bg-moss", pill: "border-moss/40 bg-moss/[0.06] text-moss", label: "released" },
  failed: { bar: "bg-rust", pill: "border-rust/40 bg-rust/[0.06] text-rust", label: "failed" },
  held: { bar: "bg-ochre", pill: "border-ochre/50 bg-ochre/[0.07] text-ochre", label: "held" },
  queued: { bar: "bg-rule", pill: "border-rule text-graphite", label: "not started" },
};

export default function RecentRuns({
  runs, stages, loaded, now,
}: { runs: RunSummary[]; stages: Stage[]; loaded: boolean; now: number }) {
  return (
    <section className="enter rounded border border-rule bg-paper p-5 shadow-spectrum" style={{ animationDelay: "260ms" }}>
      <div className="flex items-baseline justify-between">
        <h2 className="text-[13px] font-semibold">Recent runs</h2>
        {runs.length > 0 && <span className="font-mono text-[11px] text-graphite">{runs.length}</span>}
      </div>

      {!loaded ? (
        <div className="mt-3 space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-[78px]" />)}</div>
      ) : runs.length === 0 ? (
        <p className="mt-3 text-[13px] text-graphite">No runs yet. Your first brief will appear here, with its progress.</p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {runs.slice(0, 8).map((r, n) => {
            const tone = TONE[r.status] ?? TONE.queued;
            const i = stages.findIndex((s) => s.key === r.stage);
            const finished = r.status === "complete" || r.stage === "done";
            const pct = finished ? 100 : i < 0 || !stages.length ? 0 : Math.round(((i + 0.5) / stages.length) * 100);
            const where = finished ? "finished" : stages[i]?.label ?? r.stage;
            const rawUrl = r.summary?.url;
            const url = typeof rawUrl === "string" ? rawUrl : "";
            return (
              <li
                key={r.id}
                className="enter-row relative rounded border border-rule bg-paper p-3 transition-all hover:-translate-y-0.5 hover:border-signal/40 hover:shadow-spectrum"
                style={{ animationDelay: `${300 + n * 50}ms` }}
              >
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/runs/${r.id}`} className="min-w-0 text-[13.5px] font-medium leading-snug after:absolute after:inset-0 hover:text-signal">
                    {r.title}
                  </Link>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${tone.pill}`}>{tone.label}</span>
                </div>
                <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-mist">
                  <div className={`bar-grow h-full rounded-full ${tone.bar}`} style={{ width: `${pct}%` }} />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-2 font-mono text-[11px] text-graphite">
                  <span>{where}</span>
                  <span>{ago(r.created_at, now)}</span>
                </div>
                {url && (
                  <a href={url} target="_blank" rel="noreferrer" className="relative z-10 mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-signal hover:underline">
                    Open the app <Icon name="external" size={12} />
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
