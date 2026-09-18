"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function KnowledgePage() {
  const [caps, setCaps] = useState<any[]>([]);
  const [stack, setStack] = useState<any[]>([]);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => setCaps([]));
    api.stack().then(setStack).catch(() => setStack([]));
  }, []);

  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_300px]">
      <section>
        <h1 className="text-[28px] font-semibold tracking-[-0.02em]">
          What the portfolio already does
        </h1>
        <p className="mt-2 max-w-[64ch] text-[15px] leading-relaxed text-graphite">
          Every architecture decision is checked against this graph before a line of code is
          written. If a capability appears here, an agent has to justify building it again.
        </p>

        {caps.length === 0 ? (
          <p className="mt-8 text-[14px] text-graphite">
            The graph is empty. Run the indexer to load your repositories:
            <code className="ml-1 font-mono text-[13px]">docker compose run --rm indexer</code>
          </p>
        ) : (
          <ul className="mt-8 divide-y divide-rule border-y border-rule">
            {caps.map((c) => (
              <li key={c.capability} className="flex flex-wrap items-baseline gap-3 py-3">
                <span className="text-[15px]">{c.capability}</span>
                <span className="font-mono text-[12px] text-graphite">
                  {c.projects.join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <aside>
        <h2 className="text-[13px] font-medium text-graphite">House stack</h2>
        <ul className="mt-3 divide-y divide-rule border-y border-rule text-[13px]">
          {stack.map((t) => (
            <li key={t.technology} className="flex justify-between py-2">
              <span>{t.technology}</span>
              <span className="font-mono text-graphite">{t.projects}</span>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
