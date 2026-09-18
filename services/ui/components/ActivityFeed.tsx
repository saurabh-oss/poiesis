"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { agent } from "@/lib/agents";
import type { PoiesisEvent } from "@/lib/api";
import { clock } from "@/lib/progress";
import AgentAvatar from "./AgentAvatar";
import Icon from "./Icon";

type Filter = "all" | "stage" | "attention";

const TINT: Record<string, string> = {
  info: "text-ink/85",
  warn: "text-ochre",
  error: "text-rust",
  gate: "text-ochre",
};

/**
 * The run narrated as it happens. New lines slide in; the view follows the
 * latest line unless you have scrolled up to read, in which case it waits and
 * tells you how much has arrived.
 */
function ActivityFeed({
  events, stageKey, stageLabel, connected,
}: { events: PoiesisEvent[]; stageKey: string; stageLabel: string; connected: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [following, setFollowing] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  // Only lines that arrive after the first load animate; the backlog appears at rest.
  const baseline = useRef<number | null>(null);

  const rows = useMemo(
    () => events
      .map((e, i) => ({ e, i }))
      .filter(({ e }) => filter === "all" ? true : filter === "stage" ? e.stage === stageKey : e.level !== "info")
      .slice(-500),
    [events, filter, stageKey],
  );

  useEffect(() => {
    if (baseline.current === null && events.length) baseline.current = events.length;
    const el = box.current;
    if (!el) return;
    if (following) {
      el.scrollTop = el.scrollHeight;
      setUnseen(0);
    } else {
      setUnseen((n) => n + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);

  useEffect(() => {
    const el = box.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [filter, following]);

  function onScroll() {
    const el = box.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    setFollowing(atBottom);
    if (atBottom) setUnseen(0);
  }

  const attention = events.filter((e) => e.level !== "info").length;
  const tabs: { key: Filter; label: string }[] = [
    { key: "all", label: `All ${events.length}` },
    { key: "stage", label: stageLabel },
    { key: "attention", label: `Needs a look ${attention}` },
  ];

  return (
    <section className="relative flex h-[340px] flex-col overflow-hidden rounded border border-rule bg-paper shadow-spectrum">
      <div className="flex flex-wrap items-center gap-3 border-b border-rule px-4 py-2.5">
        <h2 className="text-[13px] font-semibold">Live activity</h2>
        <span className={`inline-flex items-center gap-1.5 text-[11.5px] ${connected ? "text-moss" : "text-graphite"}`}>
          <span className={connected ? "live-dot live-dot-moss" : "inline-block h-[7px] w-[7px] rounded-full bg-rule"} />
          {connected ? "connected" : "reconnecting…"}
        </span>
        <div role="tablist" className="ml-auto flex rounded border border-rule p-0.5">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={filter === t.key}
              onClick={() => setFilter(t.key)}
              className={`rounded-[3px] px-2.5 py-1 text-[12px] transition-colors ${
                filter === t.key ? "bg-ink text-paper" : "text-graphite hover:bg-mist hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div ref={box} onScroll={onScroll} className="tape flex-1 overflow-y-auto py-1.5">
        {rows.length === 0 ? (
          <p className="px-4 py-6 text-[13px] text-graphite">
            {filter === "all" ? "Nothing yet. The first agent will speak in a moment." : "Nothing here yet."}
          </p>
        ) : (
          <ol>
            {rows.map(({ e, i }) => {
              const animate = baseline.current !== null && i >= baseline.current;
              return (
                <li
                  key={e.id ?? `${i}`}
                  className={`grid grid-cols-[62px_22px_minmax(0,1fr)] items-start gap-2.5 px-4 py-1.5 ${
                    e.level === "gate" ? "bg-ochre/[0.06]" : e.level === "error" ? "bg-rust/[0.05]" : ""
                  } ${animate ? "enter-row" : ""}`}
                >
                  <time className="pt-[3px] font-mono text-[11px] tabular-nums text-graphite">{clock(e.at)}</time>
                  <AgentAvatar agentKey={e.agent} size={22} />
                  <p className="text-[13px] leading-snug">
                    <span className="font-medium">{agent(e.agent).name}</span>{" "}
                    {e.level === "gate" && <Icon name="pause" size={11} strokeWidth={2.6} className="mr-0.5 inline text-ochre" />}
                    {e.level === "error" && <Icon name="alert" size={12} className="mr-0.5 inline text-rust" />}
                    <span className={TINT[e.level] ?? TINT.info}>{e.message}</span>
                  </p>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {!following && unseen > 0 && (
        <button
          onClick={() => {
            const el = box.current;
            if (el) el.scrollTop = el.scrollHeight;
            setFollowing(true);
            setUnseen(0);
          }}
          className="enter absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-signal px-3.5 py-1.5 text-[12px] font-medium text-paper shadow-spectrum hover:bg-[#0054B6]"
        >
          <Icon name="down" size={13} /> {unseen} new
        </button>
      )}
    </section>
  );
}

export default memo(ActivityFeed);
