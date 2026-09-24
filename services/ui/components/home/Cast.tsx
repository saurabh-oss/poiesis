"use client";

import type { CSSProperties } from "react";
import { agent, CAST } from "@/lib/agents";
import type { Stage } from "@/lib/api";
import Icon from "../Icon";

/** What each agent does, as the stage glyph it owns. */
const GLYPH: Record<string, string> = {
  analyst: "discovery",
  product_owner: "vision",
  architect: "architecture",
  planner: "sprint",
  developer: "build",
  tester: "flask",
  reviewer: "review",
  release: "release",
};

/** The eight agents as a 4 × 2 relay of tiles, in the order they take the work. */
export default function Cast({ stages }: { stages: Stage[] }) {
  const decisions = stages.filter((s) => s.gate && s.gate_mode === "require" && s.gate !== "failed_story");
  return (
    <section className="enter" style={{ animationDelay: "120ms" }} aria-label="Who works on it">
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="text-[13px] font-semibold">Who works on it</h2>
        <span className="text-[12px] text-graphite">eight agents, in the order they pick it up</span>
      </div>
      <ul className="cast-grid grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {CAST.map((k, i) => {
          const a = agent(k);
          return (
            <li
              key={k}
              className="cast-tile group relative overflow-hidden rounded-lg border border-rule bg-paper p-3 shadow-spectrum"
              style={{ "--agent": a.color, animationDelay: `${160 + i * 55}ms` } as CSSProperties}
              title={`${a.name} — ${a.role}`}
            >
              <span className="cast-step absolute right-2.5 top-2 font-mono text-[10.5px] text-graphite">{String(i + 1).padStart(2, "0")}</span>
              <span className="cast-icon grid h-10 w-10 place-items-center rounded-xl text-white"
                    style={{ background: `linear-gradient(135deg, ${a.color}, ${a.color}cc)` }}>
                <Icon name={GLYPH[k] ?? "spark"} size={19} strokeWidth={1.9} />
              </span>
              <p className="mt-2.5 text-[13px] font-semibold leading-tight">{a.name}</p>
              <p className="cast-role mt-1 text-[11.5px] leading-snug text-graphite">{a.role}</p>
            </li>
          );
        })}
      </ul>
      {decisions.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-x-1.5 text-[12.5px] text-graphite">
          <span className="rounded-full bg-ochre/[0.1] px-2 py-0.5 font-semibold text-ochre">
            You decide at {decisions.length} point{decisions.length === 1 ? "" : "s"}
          </span>
          {decisions.map((d) => d.label).join(" · ")}. Everything else runs on its own.
        </p>
      )}
    </section>
  );
}
