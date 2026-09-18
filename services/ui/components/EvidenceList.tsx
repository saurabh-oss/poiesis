"use client";

import { useEffect, useState } from "react";
import { api, type Evidence } from "@/lib/api";
import Icon from "./Icon";

const KIND_ICON: Record<string, string> = { text: "file", file: "file", url: "link", audio: "audio", image: "image" };

/** Intake's output: every fragment later artifacts cite, with where it came from. */
export default function EvidenceList({ runId }: { runId: string }) {
  const [items, setItems] = useState<Evidence[] | null>(null);

  useEffect(() => {
    api.evidence(runId).then(setItems).catch(() => setItems([]));
  }, [runId]);

  if (items === null) {
    return <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-16" />)}</div>;
  }
  if (!items.length) return null;

  const sources = new Set(items.map((i) => i.source_ref)).size;
  return (
    <section className="space-y-3">
      <p className="text-[13px] text-graphite">
        <span className="font-semibold text-ink">{items.length}</span> fragment{items.length === 1 ? "" : "s"} from{" "}
        <span className="font-semibold text-ink">{sources}</span> source{sources === 1 ? "" : "s"}. Every later
        artifact cites these by id, so any claim can be traced back to what you said.
      </p>
      <ul className="grid gap-2.5">
        {items.map((e, i) => (
          <li key={e.id} className="enter rounded border border-rule bg-paper p-3" style={{ animationDelay: `${Math.min(i, 8) * 60}ms` }}>
            <div className="flex flex-wrap items-center gap-2 text-[12px]">
              <span className="grid h-6 w-6 place-items-center rounded bg-mist text-graphite">
                <Icon name={KIND_ICON[e.source_kind] ?? "file"} size={14} />
              </span>
              <span className="font-medium">{e.source_ref}</span>
              {e.locator && <span className="font-mono text-graphite">{e.locator}</span>}
              <span className="ml-auto font-mono text-[11px] text-graphite">[{e.id}]</span>
            </div>
            <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-[13px] leading-relaxed">{e.content}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
