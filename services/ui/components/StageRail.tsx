"use client";

import type { Stage } from "@/lib/api";
import { formatDuration, stageDuration, type StageSpan, type StageState } from "@/lib/progress";
import Icon from "./Icon";

const NODE: Record<StageState, string> = {
  done: "border-moss bg-moss text-paper",
  active: "node-spin border-signal bg-signal text-paper",
  gate: "station-gate border-ochre bg-ochre text-paper",
  failed: "border-rust bg-rust text-paper",
  held: "border-ochre bg-paper text-ochre",
  next: "border-signal/60 bg-paper text-signal",
  ahead: "border-rule bg-paper text-graphite",
};

const SUB_TONE: Record<StageState, string> = {
  done: "text-graphite",
  active: "text-signal",
  gate: "text-ochre",
  failed: "text-rust",
  held: "text-ochre",
  next: "text-signal/80",
  ahead: "text-transparent",
};

function connectorFor(state: StageState, next: StageState | undefined): string {
  if (!next) return "";
  if (next === "done") return "bg-moss";
  if (state === "done" && next === "active") return "flow";      // work handed forward
  if (state === "done" && next === "gate") return "bg-ochre";
  if (state === "done" && next === "failed") return "bg-rust";
  return "bg-rule";
}

export default function StageRail({
  stages, states, spans, now, selected, onSelect,
}: {
  stages: Stage[];
  states: Record<string, StageState>;
  spans: Record<string, StageSpan>;
  now: number;
  selected: string;
  onSelect: (key: string) => void;
}) {
  if (!stages.length) return <div className="skeleton h-[84px]" />;

  return (
    <nav aria-label="Stages" className="tape -mx-1 overflow-x-auto px-1 pb-1 pt-2">
      <ol className="flex min-w-[1000px]">
        {stages.map((stage, i) => {
          const state = states[stage.key] ?? "ahead";
          const next = stages[i + 1] ? states[stages[i + 1].key] ?? "ahead" : undefined;
          const isSelected = selected === stage.key;
          const took = stageDuration(stage.key, stages, spans, now, state);
          const sub =
            state === "gate" ? "your turn"
            : state === "active" ? (took !== null ? formatDuration(took) : "starting")
            : state === "failed" ? "failed"
            : state === "held" ? "held"
            : state === "next" ? "next"
            : state === "done" ? (took ? formatDuration(took) : "done")
            : "·";
          const connector = connectorFor(state, next);

          return (
            <li key={stage.key} className="relative flex-1">
              {connector && (
                <span aria-hidden className={`absolute left-1/2 right-[-50%] top-[17px] h-[2px] rounded-full ${connector}`} />
              )}
              <button
                onClick={() => onSelect(stage.key)}
                className="group relative flex w-full flex-col items-center gap-1.5 px-1 text-center"
                aria-current={isSelected ? "step" : undefined}
                title={stage.description}
              >
                <span
                  className={`relative z-10 grid h-9 w-9 place-items-center rounded-full border-2 transition-transform duration-200 group-hover:scale-110 ${NODE[state]} ${
                    isSelected ? "ring-2 ring-signal/40 ring-offset-2" : ""
                  }`}
                >
                  {state === "done" ? <Icon name="check" size={17} strokeWidth={2.4} className="pop" />
                    : state === "failed" ? <Icon name="x" size={16} strokeWidth={2.4} />
                    : state === "gate" ? <Icon name="pause" size={15} strokeWidth={2.6} />
                    : <Icon name={stage.key} size={16} />}
                </span>
                <span className={`text-[12.5px] leading-tight ${isSelected ? "font-semibold text-ink" : "text-graphite group-hover:text-ink"}`}>
                  {stage.label}
                </span>
                <span className={`h-4 font-mono text-[10.5px] tabular-nums ${SUB_TONE[state]}`}>{sub}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
