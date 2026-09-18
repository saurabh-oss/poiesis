"use client";

import type { StoryCard, StoryState } from "@/lib/progress";
import Icon from "./Icon";

const STATE: Record<StoryState, { label: string; cls: string; icon: string; working: boolean }> = {
  queued: { label: "Queued", cls: "border-rule text-graphite", icon: "clock", working: false },
  implementing: { label: "Implementing", cls: "border-signal/40 bg-signal/[0.06] text-signal", icon: "build", working: true },
  testing: { label: "Testing", cls: "border-signal/40 bg-signal/[0.06] text-signal", icon: "flask", working: true },
  repairing: { label: "Repairing", cls: "border-ochre/50 bg-ochre/[0.07] text-ochre", icon: "wrench", working: true },
  revising: { label: "Revising tests", cls: "border-ochre/50 bg-ochre/[0.07] text-ochre", icon: "flask", working: true },
  green: { label: "Green", cls: "border-moss/40 bg-moss/[0.07] text-moss", icon: "check", working: false },
  red: { label: "Red", cls: "border-rust/40 bg-rust/[0.06] text-rust", icon: "x", working: false },
  blocked: { label: "Blocked", cls: "border-rust/40 bg-rust/[0.06] text-rust", icon: "alert", working: false },
  dropped: { label: "Dropped", cls: "border-rule bg-mist text-graphite", icon: "x", working: false },
};

const REPAIR_SLOTS = 4; // three repairs, plus one against revised tests

function StoryTile({ story }: { story: StoryCard }) {
  const st = STATE[story.state];
  return (
    <article
      className={`enter relative overflow-hidden rounded border bg-paper p-3.5 transition-shadow ${
        st.working ? "border-signal/40 shadow-spectrum" : story.state === "green" ? "border-moss/30" : story.state === "red" ? "border-rust/30" : "border-rule"
      }`}
    >
      {st.working && <span aria-hidden className="flow absolute inset-x-0 top-0 h-[2px]" />}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[11px] text-graphite">{story.id}</p>
          <p className="text-[14px] font-medium leading-snug">{story.title}</p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${st.cls}`}>
          <Icon
            name={st.icon} size={12} strokeWidth={2.2}
            className={st.working ? "pulse-soft" : story.state === "green" ? "pop" : ""}
          />
          {st.label}
        </span>
      </div>
      <p className="mt-2 text-[12.5px] leading-snug text-graphite">{story.note}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-graphite">
        {story.files > 0 && <span>{story.files} files</span>}
        {story.covered && <span>{story.covered} criteria tested</span>}
        <span className="inline-flex items-center gap-1" title={`${story.attempts} repair attempt(s)`}>
          repairs
          {Array.from({ length: REPAIR_SLOTS }, (_, i) => (
            <i key={i} className={`inline-block h-1.5 w-1.5 rounded-full ${i < story.attempts ? "bg-ochre" : "bg-rule"}`} />
          ))}
        </span>
        {story.revised && <span className="text-ochre">tests revised</span>}
      </div>
    </article>
  );
}

export default function BuildBoard({ stories }: { stories: StoryCard[] }) {
  if (!stories.length) return null;
  const green = stories.filter((s) => s.state === "green").length;
  const settled = stories.filter((s) => s.state === "green" || s.state === "red" || s.state === "blocked").length;
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[13px] font-semibold">Sprint stories</p>
        <p className="font-mono text-[12px] text-graphite">
          <span className="text-moss">{green} green</span> · {settled}/{stories.length} settled
        </p>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-mist">
        <div className="h-full bg-moss transition-all duration-700" style={{ width: `${(green / stories.length) * 100}%` }} />
        <div className="h-full bg-rust/70 transition-all duration-700" style={{ width: `${((settled - green) / stories.length) * 100}%` }} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {stories.map((s) => <StoryTile key={s.id} story={s} />)}
      </div>
    </section>
  );
}
