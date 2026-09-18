import type { CSSProperties } from "react";
import { agent } from "@/lib/agents";

/** An agent's mark. `live` adds a halo in its colour and a dot in orbit: it is working now. */
export default function AgentAvatar({
  agentKey, size = 24, live = false,
}: { agentKey: string; size?: number; live?: boolean }) {
  const a = agent(agentKey);
  const style = {
    width: size,
    height: size,
    background: a.color,
    fontSize: Math.max(9, Math.round(size * 0.38)),
    "--agent": a.color,
    "--agent-glow": `${a.color}66`,
    "--orbit": `${size / 2 + 6}px`,
  } as CSSProperties;
  return (
    <span
      className={`relative inline-grid shrink-0 place-items-center rounded-full font-semibold leading-none text-white ${live ? "agent-live" : ""}`}
      style={style}
      title={a.role ? `${a.name} — ${a.role}` : a.name}
    >
      {a.initials}
      {live && <span className="agent-orbit" aria-hidden />}
    </span>
  );
}
