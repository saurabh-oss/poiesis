"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, socketFor, type Gate, type PoiesisEvent, type RunDetail, type Stage } from "@/lib/api";
import { liveStage, percent, stageDuration, stageStates, storyBoard, timeline } from "@/lib/progress";
import { useNow } from "@/lib/useNow";
import ActivityFeed from "@/components/ActivityFeed";
import BoardCard from "@/components/BoardCard";
import CodemapCard from "@/components/CodemapCard";
import DeploymentCard from "@/components/DeploymentCard";
import DomainCard from "@/components/DomainCard";
import GatePanel from "@/components/GatePanel";
import Icon from "@/components/Icon";
import IntegrationsCard from "@/components/IntegrationsCard";
import RunControls from "@/components/RunControls";
import RunHeader from "@/components/RunHeader";
import StagePanel from "@/components/StagePanel";
import StageRail from "@/components/StageRail";
import TracePanel from "@/components/TracePanel";

/** History from the API plus anything that arrived live meanwhile, without duplicates. */
function merge(base: PoiesisEvent[], extra: PoiesisEvent[]): PoiesisEvent[] {
  const seen = new Set(base.map((e) => e.id).filter(Boolean));
  return [...base, ...extra.filter((e) => !e.id || !seen.has(e.id))];
}

function Workspace({ files }: { files: string[] }) {
  const groups = new Map<string, string[]>();
  for (const f of files) {
    const top = f.includes("/") ? f.split("/")[0] : ".";
    groups.set(top, [...(groups.get(top) ?? []), f]);
  }
  return (
    <details className="group rounded border border-rule bg-paper shadow-spectrum">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-[13px] font-medium [&::-webkit-details-marker]:hidden">
        <Icon name="arrow" size={13} className="text-graphite transition-transform group-open:rotate-90" />
        Workspace
        <span className="ml-auto font-mono text-[12px] font-normal text-graphite">{files.length} files</span>
      </summary>
      <div className="tape max-h-[320px] overflow-y-auto border-t border-rule px-4 py-3 font-mono text-[12px] leading-relaxed">
        {[...groups.entries()].map(([dir, list]) => (
          <div key={dir} className="mb-2">
            <p className="text-ink">{dir === "." ? "/" : `${dir}/`}</p>
            <ul className="ml-3 text-graphite">
              {list.map((f) => <li key={f}>{dir === "." ? f : f.slice(dir.length + 1)}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </details>
  );
}

function Loading() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="flex items-center gap-5">
        <div className="skeleton h-[60px] w-[60px] rounded-full" />
        <div className="flex-1 space-y-2"><div className="skeleton h-7 w-2/5" /><div className="skeleton h-3.5 w-1/3" /></div>
      </div>
      <div className="skeleton h-14" />
      <div className="skeleton h-[96px]" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="skeleton h-[400px]" />
        <div className="skeleton h-[200px]" />
      </div>
    </div>
  );
}

export default function RunPage({ params }: { params: { id: string } }) {
  const runId = params.id;
  const [stages, setStages] = useState<Stage[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<PoiesisEvent[]>([]);
  const [gate, setGate] = useState<Gate | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [missing, setMissing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [detail, open] = await Promise.all([
        api.getRun(runId),
        api.openGate(runId).catch(() => ({ open: false }) as { open: boolean; gate?: Gate }),
      ]);
      setRun(detail);
      setGate(open.open && open.gate ? open.gate : null);
    } catch {
      setMissing(true);
    }
  }, [runId]);

  const loadHistory = useCallback(() => {
    api.events(runId).then((rows) => setEvents((live) => merge(rows, live))).catch(() => undefined);
  }, [runId]);

  useEffect(() => { api.stages().then(setStages).catch(() => undefined); }, []);
  useEffect(() => { loadHistory(); void refresh(); }, [loadHistory, refresh]);

  // One socket per run, reconnecting if the orchestrator restarts. On every
  // (re)connect the history is reloaded, so nothing said during a gap is lost.
  useEffect(() => {
    let socket: WebSocket | null = null;
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let pending: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      socket = socketFor(runId);
      socket.onopen = () => { setConnected(true); loadHistory(); void refresh(); };
      socket.onclose = () => {
        setConnected(false);
        if (!disposed) retry = setTimeout(connect, 2500);
      };
      socket.onmessage = (msg) => {
        const event: PoiesisEvent = JSON.parse(msg.data);
        setEvents((prev) => (event.id && prev.some((p) => p.id === event.id) ? prev : [...prev, event]));
        // Artifacts, gates and deployments change alongside narration. Refresh
        // the run shortly after events arrive, at most a couple of times a second.
        if (!pending) pending = setTimeout(() => { pending = null; void refresh(); }, 700);
      };
    };
    connect();
    const ping = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
    }, 25000);
    return () => {
      disposed = true;
      clearInterval(ping);
      if (retry) clearTimeout(retry);
      if (pending) clearTimeout(pending);
      socket?.close();
    };
  }, [runId, refresh, loadHistory]);

  const active = run?.status === "running" || run?.status === "waiting" || run?.status === "scheduled";
  const now = useNow(1000, active);
  const spans = useMemo(() => timeline(stages, events), [stages, events]);
  const states = useMemo(() => (run ? stageStates(stages, run, gate?.stage, spans) : {}), [stages, run, gate, spans]);
  const buildOpen = states.build === "active" || states.build === "gate";
  const stories = useMemo(() => storyBoard(events, run?.artifacts ?? [], !buildOpen), [events, run, buildOpen]);
  const failures = useMemo(() => events.filter((e) => e.level === "error").slice(-6), [events]);

  if (missing) {
    return (
      <div className="enter mx-auto max-w-[520px] rounded border border-rule bg-paper p-8 text-center shadow-spectrum">
        <p className="text-[18px] font-semibold">This run could not be found</p>
        <p className="mt-2 text-[14px] text-graphite">It may have been removed, or the orchestrator is not answering on port 8080.</p>
        <Link href="/" className="mt-5 inline-flex items-center gap-1.5 rounded bg-signal px-4 py-2 text-[13px] font-medium text-paper hover:bg-[#0054B6]">
          Back to runs <Icon name="arrow" size={14} />
        </Link>
      </div>
    );
  }
  if (!run || !stages.length) return <Loading />;

  const live = liveStage(stages, run, spans);
  // A finished run opens on its release — the version, the address and the notes —
  // rather than on harvest, the last stage but the one with least to show.
  const landing = run.status === "complete" && stages.some((s) => s.key === "release") ? "release" : live;
  const selected = picked && stages.some((s) => s.key === picked) ? picked : landing;
  const stage = stages.find((s) => s.key === selected) ?? stages[0];
  const pct = run.status === "complete" ? 100 : percent(stages, states, stories);
  const stageEvents = events.filter((e) => e.stage === stage.key);

  const gatePanel = gate ? <GatePanel runId={runId} gate={gate} onResolved={refresh} /> : null;
  const deployCard = (
    <DeploymentCard
      runId={runId}
      deployment={run.deployment}
      canDeploy={run.files.includes("docker-compose.yml") && run.status !== "running"}
      onChange={refresh}
    />
  );

  return (
    <div className="space-y-6">
      <RunHeader run={run} stages={stages} live={live} spans={spans} events={events} gate={gate} pct={pct} now={now} />

      <div className="enter rounded border border-rule bg-paper px-3 pb-2 pt-3 shadow-spectrum" style={{ animationDelay: "60ms" }}>
        <StageRail
          stages={stages}
          states={states}
          spans={spans}
          now={now}
          selected={selected}
          onSelect={(k) => setPicked(k === landing ? null : k)}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <StagePanel
          key={stage.key}
          runId={runId}
          stage={stage}
          state={states[stage.key] ?? "ahead"}
          span={spans[stage.key]}
          stageEvents={stageEvents}
          artifacts={run.artifacts.filter((a) => a.stage === stage.key)}
          stories={stories}
          gate={gate}
          now={now}
          duration={stageDuration(stage.key, stages, spans, now, states[stage.key])}
          isLive={selected === live}
          runActive={active}
          failureEvents={failures}
          onBackToLive={() => setPicked(null)}
        />
        <aside className="space-y-6">
          {/* A release decision arrives with the app one click away; any other
              decision comes first, because it is what the run is waiting on. */}
          {gate?.kind === "approve_release" ? <>{deployCard}{gatePanel}</> : <>{gatePanel}{deployCard}</>}
          <DomainCard runId={runId} active={active} />
          <BoardCard runId={runId} active={active} />
          {run.files.includes("docker-compose.yml") && <CodemapCard runId={runId} />}
          <RunControls run={run} onChange={refresh} />
          <IntegrationsCard runId={runId} active={active} />
          {run.files.length > 0 && <Workspace files={run.files} />}
        </aside>
      </div>

      <TracePanel runId={runId} active={active} />

      <ActivityFeed events={events} stageKey={stage.key} stageLabel={stage.label} connected={connected} />
    </div>
  );
}
