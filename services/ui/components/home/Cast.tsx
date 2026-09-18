"use client";

import { agent, CAST } from "@/lib/agents";
import type { Stage } from "@/lib/api";
import AgentAvatar from "../AgentAvatar";

export default function Cast({ stages }: { stages: Stage[] }) {
  const decisions = stages.filter((s) => s.gate && s.gate_mode === "require" && s.gate !== "failed_story");
  return (
    <section className="enter rounded border border-rule bg-paper p-5 shadow-spectrum" style={{ animationDelay: "180ms" }}>
      <h2 className="text-[13px] font-semibold">Who works on it</h2>
      <ul className="mt-3 space-y-3">
        {CAST.map((k, i) => {
          const a = agent(k);
          return (
            <li key={k} className="enter-row flex items-start gap-2.5" style={{ animationDelay: `${220 + i * 40}ms` }}>
              <AgentAvatar agentKey={k} size={28} />
              <div>
                <p className="text-[13px] font-medium leading-tight">{a.name}</p>
                <p className="text-[12px] leading-snug text-graphite">{a.role}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {decisions.length > 0 && (
        <div className="mt-4 rounded bg-ochre/[0.07] p-3 text-[12.5px]">
          <p className="font-semibold text-ochre">You decide at {decisions.length} points</p>
          <p className="mt-1 leading-snug text-graphite">
            {decisions.map((d) => d.label).join(" · ")}. Everything else runs on its own.
          </p>
        </div>
      )}
    </section>
  );
}
