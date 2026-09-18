"use client";

import type { Stage } from "@/lib/api";
import Icon from "../Icon";

/** The value stream as a signal travelling stage to stage, on a loop. */
export default function StreamBand({ stages }: { stages: Stage[] }) {
  if (!stages.length) return <div className="skeleton h-[96px]" />;
  const step = 0.6;
  const cycle = `${stages.length * step}s`;

  return (
    <div className="tape overflow-x-auto pb-1">
      <ol className="flex min-w-[900px] items-start">
        {stages.map((s, i) => {
          const decides = s.gate && s.gate_mode === "require" && s.gate !== "failed_story";
          return (
            <li key={s.key} className="relative flex flex-1 flex-col items-center gap-1.5 text-center" title={s.description}>
              {i < stages.length - 1 && (
                <span
                  aria-hidden
                  className="travel-line absolute left-1/2 right-[-50%] top-[17px] h-[2px] rounded-full bg-rule"
                  style={{ animationDelay: `${i * step + step / 2}s`, animationDuration: cycle }}
                />
              )}
              <span
                className="travel relative z-10 grid h-9 w-9 place-items-center rounded-full border-2 border-rule bg-paper text-graphite"
                style={{ animationDelay: `${i * step}s`, animationDuration: cycle }}
              >
                <Icon name={s.key} size={16} />
              </span>
              <span className="text-[12px] leading-tight text-graphite">{s.label}</span>
              <span className={`rounded-full px-1.5 text-[10px] font-medium ${decides ? "bg-ochre/10 text-ochre" : "text-transparent"}`}>
                you decide
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
