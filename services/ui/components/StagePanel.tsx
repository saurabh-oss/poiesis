"use client";

import { agent } from "@/lib/agents";
import type { Artifact, Gate, PoiesisEvent, Stage } from "@/lib/api";
import {
  clock, formatDuration, latestByKind,
  type StageSpan, type StageState, type StoryCard,
} from "@/lib/progress";
import AgentAvatar from "./AgentAvatar";
import ArtifactView from "./ArtifactView";
import BuildBoard from "./BuildBoard";
import EvidenceList from "./EvidenceList";
import Icon from "./Icon";

const CHIP: Record<StageState, { label: string; cls: string }> = {
  done: { label: "Done", cls: "border-moss/40 bg-moss/[0.07] text-moss" },
  active: { label: "In progress", cls: "border-signal/40 bg-signal/[0.07] text-signal" },
  gate: { label: "Waiting on you", cls: "border-ochre/50 bg-ochre/[0.08] text-ochre" },
  failed: { label: "Failed", cls: "border-rust/40 bg-rust/[0.06] text-rust" },
  held: { label: "Held", cls: "border-ochre/50 bg-ochre/[0.08] text-ochre" },
  next: { label: "Up next", cls: "border-signal/30 text-signal" },
  ahead: { label: "Not started", cls: "border-rule text-graphite" },
};

const BADGE: Record<StageState, string> = {
  done: "bg-moss/10 text-moss",
  active: "bg-signal text-paper",
  gate: "bg-ochre/10 text-ochre",
  failed: "bg-rust/10 text-rust",
  held: "bg-ochre/10 text-ochre",
  next: "bg-signal/10 text-signal",
  ahead: "bg-mist text-graphite",
};

const KIND_LABEL: Record<string, string> = {
  discovery: "The Analyst's read of your brief",
  vision: "Product vision",
  backlog: "Product backlog",
  architecture: "Architecture and reuse plan",
  sprint: "Sprint plan",
  scaffold: "Application skeleton",
  test_report: "Test report",
  review: "Review verdict",
  deployment: "Deployment",
  release: "Release",
};

function lowerFirst(s: string): string {
  return s ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

/** A placeholder in the shape of what the stage is about to produce. */
function Skeleton({ kind }: { kind: string }) {
  if (kind === "backlog") {
    return (
      <div className="grid gap-2.5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2 rounded border border-rule p-3">
            <div className="skeleton h-3 w-24" /><div className="skeleton h-4 w-3/5" /><div className="skeleton h-3 w-4/5" />
          </div>
        ))}
      </div>
    );
  }
  if (kind === "architecture") {
    return (
      <div className="space-y-2.5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="grid grid-cols-[2fr_1fr_2fr] gap-3">
            <div className="skeleton h-4" /><div className="skeleton h-4" /><div className="skeleton h-4" />
          </div>
        ))}
      </div>
    );
  }
  if (kind === "discovery") {
    return (
      <div className="space-y-2.5">
        <div className="skeleton h-14" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-2 rounded border border-rule p-3">
            <div className="skeleton h-4 w-12" /><div className="skeleton h-4 flex-1" />
          </div>
        ))}
      </div>
    );
  }
  if (kind === "review") {
    return (
      <div className="space-y-3">
        {[80, 55, 70, 45, 65].map((w, i) => (
          <div key={i} className="space-y-1.5"><div className="skeleton h-3 w-40" /><div className="skeleton h-1.5" style={{ width: `${w}%` }} /></div>
        ))}
      </div>
    );
  }
  if (kind === "sprint") {
    return (
      <div className="space-y-2.5">
        <div className="skeleton h-12" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-3"><div className="skeleton h-7 w-7 rounded-full" /><div className="skeleton h-7 flex-1" /></div>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-2.5">
      <div className="skeleton h-6 w-2/5" />
      <div className="skeleton h-3.5 w-full" /><div className="skeleton h-3.5 w-11/12" /><div className="skeleton h-3.5 w-4/5" />
      <div className="skeleton mt-4 h-3.5 w-3/5" />
    </div>
  );
}

function LiveWork({
  stage, span, now, showSkeleton,
}: { stage: Stage; span: StageSpan | undefined; now: number; showSkeleton: boolean }) {
  const who = span?.lastWorker?.agent ?? stage.agents[0] ?? "system";
  const a = agent(who);
  return (
    <div className="enter space-y-4 rounded border border-signal/25 bg-signal/[0.035] p-4">
      <div className="flex items-center gap-3">
        <AgentAvatar agentKey={who} size={38} live />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold">
            {a.name} is working<span className="typing text-signal" aria-hidden><span /><span /><span /></span>
          </p>
          <p className="caret truncate text-[13.5px] text-graphite">
            {span?.lastWorker?.message ?? `Starting on the ${lowerFirst(stage.label)}`}
          </p>
        </div>
        {span?.start ? (
          <span className="shrink-0 font-mono text-[13px] tabular-nums text-signal">{formatDuration(now - span.start)}</span>
        ) : null}
      </div>
      {showSkeleton && (
        <div>
          <p className="mb-2.5 text-[11.5px] font-semibold uppercase tracking-[0.07em] text-graphite">
            Taking shape: {lowerFirst(stage.produces || stage.label)}
          </p>
          <Skeleton kind={stage.key} />
        </div>
      )}
    </div>
  );
}

function GateNote({ stage }: { stage: Stage }) {
  if (!stage.gate) {
    return (
      <p className="flex items-start gap-2 text-[13px] text-graphite">
        <Icon name="arrow" size={15} className="mt-0.5 shrink-0 text-moss" />
        Runs without stopping. Its output appears here the moment it lands.
      </p>
    );
  }
  if (stage.gate === "failed_story") {
    return (
      <p className="flex items-start gap-2 text-[13px] text-graphite">
        <Icon name="pause" size={15} className="mt-0.5 shrink-0 text-ochre" />{stage.asks}
      </p>
    );
  }
  if (stage.gate_mode === "auto") {
    return (
      <p className="flex items-start gap-2 text-[13px] text-graphite">
        <Icon name="check" size={15} className="mt-0.5 shrink-0 text-moss" />
        Approved automatically by your domain pack, so it will not stop to ask.
      </p>
    );
  }
  return (
    <div className="flex items-start gap-3 rounded border border-ochre/40 bg-ochre/[0.06] p-3.5">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ochre text-paper">
        <Icon name="pause" size={13} strokeWidth={2.6} />
      </span>
      <div>
        <p className="text-[13px] font-semibold text-ochre">You decide here</p>
        <p className="text-[13px]">{stage.asks}</p>
      </div>
    </div>
  );
}

function UpNext({ stage, state }: { stage: Stage; state: StageState }) {
  return (
    <div className="enter space-y-5">
      <div className="rounded border border-rule bg-mist/60 p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-graphite">
          {state === "next" ? "Up next" : "Later in this run"}
        </p>
        <p className="mt-1.5 text-[15px] leading-relaxed">
          {stage.produces ? `This stage produces ${lowerFirst(stage.produces)}.` : stage.description}
        </p>
      </div>
      {stage.agents.length > 0 && (
        <div>
          <p className="text-[12px] font-medium text-graphite">Who does the work</p>
          <ul className="mt-2 grid gap-2.5 sm:grid-cols-2">
            {stage.agents.map((k) => {
              const a = agent(k);
              return (
                <li key={k} className="flex items-start gap-3 rounded border border-rule bg-paper p-3">
                  <AgentAvatar agentKey={k} size={30} />
                  <div>
                    <p className="text-[13.5px] font-medium">{a.name}</p>
                    <p className="text-[12.5px] leading-snug text-graphite">{a.role}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <GateNote stage={stage} />
    </div>
  );
}

function GateCallout({ gate }: { gate: Gate | null }) {
  return (
    <a href="#gate" className="enter flex items-start gap-3 rounded border border-ochre/40 bg-ochre/[0.06] p-4 transition-colors hover:bg-ochre/[0.1]">
      <span className="station-gate grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ochre text-paper">
        <Icon name="pause" size={14} strokeWidth={2.6} />
      </span>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-ochre">Paused for your decision</p>
        <p className="mt-0.5 text-[14px]">{gate?.question ?? "This stage is waiting on you."}</p>
        <p className="mt-1 text-[12.5px] text-graphite">Your answer goes in the panel alongside. Nothing runs until you give it.</p>
      </div>
    </a>
  );
}

function Failure({ events }: { events: PoiesisEvent[] }) {
  if (!events.length) return null;
  let trace: unknown;
  for (let i = events.length - 1; i >= 0; i--) if (events[i].data?.traceback) { trace = events[i].data.traceback; break; }
  return (
    <div className="enter space-y-2 rounded border border-rust/30 bg-rust/[0.04] p-4">
      <p className="flex items-center gap-2 text-[13px] font-semibold text-rust"><Icon name="alert" size={15} />What went wrong</p>
      <ul className="space-y-1 text-[13px]">
        {events.slice(-4).map((e, i) => <li key={e.id ?? i}>{e.message}</li>)}
      </ul>
      {trace ? (
        <details className="text-[12px]">
          <summary className="cursor-pointer text-graphite">Technical detail</summary>
          <pre className="tape mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap rounded bg-paper p-2 font-mono text-[11px] text-graphite">{String(trace)}</pre>
        </details>
      ) : null}
    </div>
  );
}

function StageLog({ events, open }: { events: PoiesisEvent[]; open: boolean }) {
  if (!events.length) return null;
  return (
    <details open={open} className="group rounded border border-rule">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-[13px] font-medium [&::-webkit-details-marker]:hidden">
        <Icon name="arrow" size={13} className="text-graphite transition-transform group-open:rotate-90" />
        What happened in this stage
        <span className="font-mono text-[12px] font-normal text-graphite">({events.length})</span>
      </summary>
      <ol className="tape max-h-[360px] space-y-2 overflow-y-auto border-t border-rule px-4 py-3">
        {events.slice(-80).map((e, i) => (
          <li key={e.id ?? i} className="grid grid-cols-[62px_20px_minmax(0,1fr)] items-start gap-2.5">
            <time className="pt-0.5 font-mono text-[11px] tabular-nums text-graphite">{clock(e.at)}</time>
            <AgentAvatar agentKey={e.agent} size={20} />
            <p className={`text-[13px] leading-snug ${
              e.level === "error" ? "text-rust" : e.level === "warn" || e.level === "gate" ? "text-ochre" : ""
            }`}>
              {e.message}
            </p>
          </li>
        ))}
      </ol>
    </details>
  );
}

export default function StagePanel({
  runId, stage, state, span, stageEvents, artifacts, stories, gate, now, duration,
  isLive, runActive, failureEvents, onBackToLive,
}: {
  runId: string;
  stage: Stage;
  state: StageState;
  span: StageSpan | undefined;
  stageEvents: PoiesisEvent[];
  artifacts: Artifact[];
  stories: StoryCard[];
  gate: Gate | null;
  now: number;
  duration: number | null;
  isLive: boolean;
  runActive: boolean;
  failureEvents: PoiesisEvent[];
  onBackToLive: () => void;
}) {
  const shown = latestByKind(artifacts);
  const chip = CHIP[state];
  const working = state === "active";
  const upcoming = state === "next" || state === "ahead";
  const isBuild = stage.key === "build";
  const isIntake = stage.key === "intake";
  const people = span?.agents.length ? span.agents : stage.agents;

  return (
    <section className="min-h-[400px] rounded border border-rule bg-paper p-6 shadow-spectrum">
      <div className="enter flex flex-wrap items-start gap-x-4 gap-y-3">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg ${BADGE[state]}`}>
          <Icon name={stage.key} size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-[19px] font-semibold tracking-[-0.01em]">{stage.label}</h2>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium ${chip.cls}`}>
              {working && <span className="live-dot" />}
              {chip.label}
              {!upcoming && duration !== null && duration > 0 && <span className="font-mono">· {formatDuration(duration)}</span>}
            </span>
          </div>
          <p className="mt-1 max-w-[70ch] text-[13.5px] text-graphite">{stage.description}</p>
        </div>
        <div className="flex items-center gap-3">
          {people.length > 0 && (
            <div className="flex -space-x-1.5">
              {people.map((k) => (
                <span key={k} className="rounded-full ring-2 ring-paper">
                  <AgentAvatar agentKey={k} size={26} live={working && span?.lastWorker?.agent === k} />
                </span>
              ))}
            </div>
          )}
          {!isLive && runActive && (
            <button
              onClick={onBackToLive}
              className="inline-flex items-center gap-1.5 rounded border border-signal/40 px-2.5 py-1 text-[12px] font-medium text-signal hover:bg-signal/[0.06]"
            >
              <span className="live-dot" /> Back to live
            </button>
          )}
        </div>
      </div>

      <div className="mt-6 space-y-6">
        {upcoming ? (
          <UpNext stage={stage} state={state} />
        ) : (
          <>
            {state === "gate" && <GateCallout gate={gate} />}
            {state === "failed" && <Failure events={failureEvents} />}
            {working && <LiveWork stage={stage} span={span} now={now} showSkeleton={!isBuild && !isIntake && shown.length === 0} />}
            {isBuild && <BuildBoard stories={stories} />}
            {isIntake && <EvidenceList runId={runId} />}
            {shown.map((a, i) => (
              <article key={a.id} className="enter" style={{ animationDelay: `${i * 80}ms` }}>
                <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-rule pb-2">
                  <p className="text-[12px] font-semibold uppercase tracking-[0.07em] text-graphite">
                    {KIND_LABEL[a.kind] ?? a.kind.replace(/_/g, " ")}
                  </p>
                  {a.version > 1 && (
                    <span className="rounded-full bg-ochre/10 px-2 py-0.5 text-[11px] font-medium text-ochre">revised · v{a.version}</span>
                  )}
                  <span className="ml-auto font-mono text-[11px] text-graphite">{clock(a.created_at)}</span>
                </div>
                <ArtifactView artifact={a} />
              </article>
            ))}
            {state === "done" && !shown.length && !stageEvents.length && !isBuild && !isIntake && (
              <p className="text-[13.5px] text-graphite">Nothing was recorded for this stage.</p>
            )}
            <StageLog events={stageEvents} open={!working && shown.length === 0 && !isBuild && !isIntake} />
          </>
        )}
      </div>
    </section>
  );
}
