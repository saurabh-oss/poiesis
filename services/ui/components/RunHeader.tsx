"use client";

import type { CSSProperties } from "react";
import { agent } from "@/lib/agents";
import type { Gate, PoiesisEvent, RunDetail, Stage } from "@/lib/api";
import { formatDuration, type StageSpan } from "@/lib/progress";
import AgentAvatar from "./AgentAvatar";
import Icon from "./Icon";

const PILL: Record<string, string> = {
  running: "border-signal/40 bg-signal/[0.08] text-signal",
  waiting: "border-ochre/50 bg-ochre/[0.08] text-ochre",
  complete: "border-moss/40 bg-moss/[0.08] text-moss",
  released: "border-moss/40 bg-moss/[0.08] text-moss",
  failed: "border-rust/40 bg-rust/[0.08] text-rust",
  held: "border-ochre/50 bg-ochre/[0.08] text-ochre",
  queued: "border-rule bg-mist text-graphite",
  scheduled: "border-signal/30 bg-signal/[0.05] text-signal",
  cancelled: "border-rule bg-mist text-graphite",
};

const LABEL: Record<string, string> = {
  running: "Working",
  waiting: "Waiting on you",
  complete: "Complete",
  released: "Released",
  failed: "Failed",
  held: "Release held",
  queued: "Not started",
  scheduled: "Queued for a slot",
  cancelled: "Stopped",
};

const RING: Record<string, string> = {
  failed: "#D31510", waiting: "#DA7B11", held: "#DA7B11",
  complete: "#007A4D", released: "#007A4D",
};

function ProgressRing({ pct, status }: { pct: number; status: string }) {
  const r = 24;
  const circ = 2 * Math.PI * r;
  const color = RING[status] ?? "#0265DC";
  return (
    <div className="relative h-[60px] w-[60px] shrink-0">
      <svg viewBox="0 0 60 60" className="h-full w-full -rotate-90" aria-hidden>
        <circle cx="30" cy="30" r={r} fill="none" stroke="#E1E1E1" strokeWidth="5" />
        <circle
          className="ring-draw" cx="30" cy="30" r={r} fill="none" stroke={color} strokeWidth="5"
          strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - pct / 100)}
          style={{ "--circ": circ } as CSSProperties}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center font-mono text-[13px] font-semibold tabular-nums" style={{ color }}>
        {status === "complete" ? <Icon name="check" size={22} strokeWidth={2.6} className="pop" /> : `${pct}%`}
      </span>
      {status === "complete" && <Burst />}
      <span className="sr-only">{pct}% complete</span>
    </div>
  );
}

/** One small burst when a run finishes. It plays once, on mount. */
function Burst() {
  const colors = ["#0265DC", "#007A4D", "#DA7B11", "#8A3FD6", "#C8336E", "#0D8A80"];
  return (
    <span aria-hidden className="burst pointer-events-none absolute inset-0">
      {Array.from({ length: 14 }, (_, i) => {
        const angle = (i / 14) * Math.PI * 2;
        const dist = 36 + (i % 3) * 9;
        return (
          <i
            key={i}
            style={{
              background: colors[i % colors.length],
              "--dx": `${Math.cos(angle) * dist}px`,
              "--dy": `${Math.sin(angle) * dist}px`,
              animationDelay: `${(i % 4) * 45}ms`,
            } as CSSProperties}
          />
        );
      })}
    </span>
  );
}

function NowStrip({
  run, stageLabel, span, latest, gate, now,
}: {
  run: RunDetail; stageLabel: string; span: StageSpan | undefined;
  latest: PoiesisEvent | null; gate: Gate | null; now: number;
}) {
  const status = run.status;
  const url = run.deployment?.status === "running" ? run.deployment.url : "";

  if (status === "waiting") {
    return (
      <div className="enter flex flex-wrap items-center gap-3 rounded border border-ochre/40 bg-ochre/[0.06] px-4 py-3">
        <span className="station-gate grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ochre text-paper">
          <Icon name="pause" size={14} strokeWidth={2.6} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-ochre">Waiting on you · {stageLabel}</p>
          <p className="truncate text-[14px]">{gate?.question ?? "A decision is needed before the run can continue."}</p>
        </div>
        <a href="#gate" className="inline-flex items-center gap-1.5 rounded bg-ochre px-3.5 py-1.5 text-[13px] font-medium text-paper hover:brightness-95">
          Answer <Icon name="down" size={14} />
        </a>
      </div>
    );
  }
  if (status === "complete" || status === "released") {
    return (
      <div className="enter flex flex-wrap items-center gap-3 rounded border border-moss/30 bg-moss/[0.06] px-4 py-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-moss text-paper">
          <Icon name="check" size={16} strokeWidth={2.6} className="pop" />
        </span>
        <p className="min-w-0 flex-1 text-[14px]">
          {status === "released" ? "Released. Recording what this run learned." : "Every stage ran. The increment is built, reviewed and released."}
        </p>
        {url && (
          <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded bg-moss px-3.5 py-1.5 text-[13px] font-medium text-paper hover:brightness-95">
            Open the app <Icon name="external" size={14} />
          </a>
        )}
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="enter flex items-start gap-3 rounded border border-rust/30 bg-rust/[0.05] px-4 py-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-rust text-paper"><Icon name="alert" size={16} /></span>
        <p className="min-w-0 flex-1 text-[14px]">{latest?.message ?? "The run stopped with an error."}</p>
      </div>
    );
  }
  if (status === "held") {
    return (
      <div className="enter flex items-center gap-3 rounded border border-ochre/40 bg-ochre/[0.05] px-4 py-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 border-ochre text-ochre"><Icon name="pause" size={14} strokeWidth={2.6} /></span>
        <p className="min-w-0 flex-1 text-[14px]">You held the release. {url ? "The app keeps running so you can keep trying it." : ""}</p>
      </div>
    );
  }
  if (status === "queued") {
    return (
      <div className="flex items-center gap-3 rounded border border-rule bg-mist/60 px-4 py-3 text-[14px] text-graphite">
        <Icon name="clock" size={18} /> Not started yet.
      </div>
    );
  }
  if (status === "scheduled") {
    return (
      <div className="flex items-center gap-3 rounded border border-signal/25 bg-signal/[0.04] px-4 py-3 text-[14px]">
        <Icon name="clock" size={18} className="text-signal" /> Waiting for another run to finish with the models. It starts on its own.
      </div>
    );
  }
  if (status === "cancelled") {
    return (
      <div className="flex items-center gap-3 rounded border border-rule bg-mist/60 px-4 py-3 text-[14px] text-graphite">
        <Icon name="pause" size={16} strokeWidth={2.6} /> Stopped where it was. Everything finished so far is kept.
      </div>
    );
  }

  const who = latest?.agent ?? "system";
  const a = agent(who);
  return (
    <div className="enter relative flex items-center gap-3 overflow-hidden rounded border border-signal/25 bg-signal/[0.04] px-4 py-3">
      <span aria-hidden className="flow absolute inset-x-0 top-0 h-[2px]" />
      <AgentAvatar agentKey={who} size={32} live />
      <div className="min-w-0 flex-1">
        <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-signal">
          {a.name} is working<span className="typing" aria-hidden><span /><span /><span /></span>
        </p>
        <p className="truncate text-[14px]">{latest?.message ?? "Getting started"}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-[12px] text-graphite">{stageLabel}</p>
        <p className="font-mono text-[13px] tabular-nums text-signal">
          {span?.start ? formatDuration(now - span.start) : ""}
        </p>
      </div>
    </div>
  );
}

export default function RunHeader({
  run, stages, live, spans, events, gate, pct, now,
}: {
  run: RunDetail; stages: Stage[]; live: string; spans: Record<string, StageSpan>;
  events: PoiesisEvent[]; gate: Gate | null; pct: number; now: number;
}) {
  const status = run.status;
  const stageLabel = stages.find((s) => s.key === live)?.label ?? live;
  const span = spans[live];
  // The latest line worth showing: the worker's own narration, not the
  // governance "waiting on a human" echo, unless something has gone wrong.
  let latest: PoiesisEvent | null = null;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (status === "failed" ? e.level === "error" : e.agent !== "governance") { latest = e; break; }
  }
  const firstAt = events.find((e) => e.at)?.at;
  let lastAt: string | undefined;
  for (let i = events.length - 1; i >= 0; i--) if (events[i].at) { lastAt = events[i].at; break; }
  const finished = status === "complete" || status === "failed" || status === "held" || status === "cancelled";
  const total = firstAt ? (finished && lastAt ? Date.parse(lastAt) : now) - Date.parse(firstAt) : null;

  return (
    <header className="enter space-y-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <ProgressRing pct={pct} status={status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{run.title}</h1>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${PILL[status] ?? PILL.queued}`}>
              {status === "running" && <span className="live-dot" />}
              {status === "waiting" && <span className="live-dot live-dot-ochre" />}
              {LABEL[status] ?? status}
            </span>
          </div>
          <p className="mt-1 font-mono text-[12px] text-graphite">
            {run.id} · {run.evidence_count} evidence fragment{run.evidence_count === 1 ? "" : "s"} · {run.files.length} files
            {total !== null && total > 0 && ` · ${finished ? "took" : "running for"} ${formatDuration(total)}`}
          </p>
        </div>
      </div>
      <NowStrip run={run} stageLabel={stageLabel} span={span} latest={latest} gate={gate} now={now} />
    </header>
  );
}
