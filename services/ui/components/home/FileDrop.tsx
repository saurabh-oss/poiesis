"use client";

import { useRef, useState } from "react";
import Icon from "../Icon";

function iconFor(file: File): string {
  const type = file.type;
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("audio/") || type.startsWith("video/")) return "audio";
  return "file";
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileDrop({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function add(list: FileList | null) {
    if (!list) return;
    const next = [...files];
    for (const f of Array.from(list)) {
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    onChange(next);
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded border-2 border-dashed px-4 py-6 text-center transition-colors ${
          over ? "drop-active border-signal bg-signal/[0.05]" : "border-rule hover:border-graphite/50 hover:bg-mist/60"
        }`}
      >
        <span className={`grid h-10 w-10 place-items-center rounded-full transition-all ${over ? "scale-110 bg-signal text-paper" : "bg-mist text-graphite"}`}>
          <Icon name="upload" size={18} />
        </span>
        <p className="text-[13px] font-medium">{over ? "Drop to add" : "Drop files here, or click to browse"}</p>
        <p className="text-[11.5px] text-graphite">Documents, whiteboard photos, a recorded call. Nothing leaves this machine.</p>
        <input
          ref={input} type="file" multiple hidden
          accept=".pdf,.docx,.md,.txt,.csv,.json,.yaml,.yml,.png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.ogg,.mp4,.webm"
          onChange={(e) => { add(e.target.files); e.target.value = ""; }}
        />
      </div>
      {files.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {files.map((f, i) => (
            <li key={`${f.name}-${f.size}`} className="enter-row flex items-center gap-2 rounded border border-rule bg-paper px-2.5 py-1.5 text-[12.5px]">
              <Icon name={iconFor(f)} size={15} className="shrink-0 text-graphite" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <span className="font-mono text-[11px] text-graphite">{size(f.size)}</span>
              <button
                type="button"
                aria-label={`Remove ${f.name}`}
                onClick={() => onChange(files.filter((_, j) => j !== i))}
                className="rounded p-0.5 text-graphite hover:bg-mist hover:text-rust"
              >
                <Icon name="x" size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
