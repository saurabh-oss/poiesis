"use client";

import { useState } from "react";
import Icon from "../Icon";

function host(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

export default function LinkChips({ links, onChange }: { links: string[]; onChange: (links: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  function add() {
    const value = draft.trim();
    if (!value) return;
    if (!/^https?:\/\/\S+\.\S+/.test(value)) {
      setError("A link starts with http:// or https://");
      return;
    }
    if (!links.includes(value)) onChange([...links, value]);
    setDraft("");
    setError("");
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setError(""); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="https://…"
          aria-label="Add a link"
          className="min-w-0 flex-1 border border-rule px-3 py-2 font-mono text-[12.5px]"
        />
        <button type="button" onClick={add} className="rounded border border-rule bg-paper px-3.5 text-[13px] hover:bg-mist">
          Add
        </button>
      </div>
      {error ? (
        <p className="mt-1.5 text-[12px] text-rust">{error}</p>
      ) : (
        <p className="mt-1.5 text-[11.5px] text-graphite">Poiesis reads each page and cites it like any other source.</p>
      )}
      {links.length > 0 && (
        <ul className="mt-2.5 flex flex-wrap gap-1.5">
          {links.map((l) => (
            <li key={l} className="enter-row inline-flex max-w-full items-center gap-1.5 rounded-full border border-rule bg-mist px-2.5 py-1 text-[12px]">
              <Icon name="link" size={12} className="shrink-0 text-graphite" />
              <span className="truncate" title={l}>{host(l)}</span>
              <button
                type="button"
                aria-label={`Remove ${l}`}
                onClick={() => onChange(links.filter((x) => x !== l))}
                className="rounded-full text-graphite hover:text-rust"
              >
                <Icon name="x" size={11} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
