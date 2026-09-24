"use client";

import type { PlaneCounts } from "@/lib/api";

/** Plane's state groups, in board order, with the colours the console uses for them. */
export const GROUPS: { key: keyof PlaneCounts; label: string; color: string }[] = [
  { key: "backlog", label: "Backlog", color: "#B1B1B1" },
  { key: "unstarted", label: "Todo", color: "#7E84FA" },
  { key: "started", label: "In progress", color: "#F68511" },
  { key: "completed", label: "Done", color: "#007A4D" },
  { key: "cancelled", label: "Cancelled", color: "#D31510" },
];

export const PRIORITY: Record<string, { label: string; color: string; bars: number }> = {
  urgent: { label: "Urgent", color: "#D31510", bars: 4 },
  high: { label: "High", color: "#E68619", bars: 3 },
  medium: { label: "Medium", color: "#0265DC", bars: 2 },
  low: { label: "Low", color: "#8E8E8E", bars: 1 },
};

export function PriorityMark({ priority }: { priority: string | null }) {
  const p = PRIORITY[priority ?? ""] ?? null;
  if (!p) return null;
  return (
    <span className="inline-flex items-end gap-[2px]" title={`${p.label} priority`} aria-label={`${p.label} priority`}>
      {[1, 2, 3, 4].map((i) => (
        <span key={i} className="w-[3px] rounded-sm" style={{ height: 3 + i * 2.5, background: i <= p.bars ? p.color : "#E1E1E1" }} />
      ))}
    </span>
  );
}

/** A segmented progress bar: how many work items sit in each state group. */
export function GroupBar({ counts, height = 8 }: { counts: PlaneCounts; height?: number }) {
  const total = GROUPS.reduce((a, g) => a + (counts[g.key] || 0), 0) || 1;
  return (
    <div className="flex overflow-hidden rounded-full bg-mist" style={{ height }}>
      {GROUPS.map((g, i) => counts[g.key] ? (
        <span key={g.key} className="bar-grow h-full" title={`${g.label}: ${counts[g.key]}`}
              style={{ width: `${(100 * counts[g.key]) / total}%`, background: g.color, animationDelay: `${120 + i * 90}ms` }} />
      ) : null)}
    </div>
  );
}
