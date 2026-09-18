"use client";

import { useState } from "react";
import { api, type Gate } from "@/lib/api";

export default function GatePanel({ runId, gate, onResolved }: {
  runId: string; gate: Gate; onResolved: () => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: string) {
    setBusy(decision);
    setError(null);
    try {
      await api.resolveGate(runId, { decision, notes, answers, actor: "stakeholder" });
      onResolved();
    } catch (e: any) {
      setError(e.message ?? "The decision could not be recorded. Try again.");
      setBusy(null);
    }
  }

  return (
    <aside id="gate" className="gate-attention scroll-mt-24 rounded border border-ochre/60 bg-[#FFF8F0] shadow-spectrum">
      <div className="border-b border-ochre/40 px-5 py-3">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ochre">
          <span className="live-dot live-dot-ochre" />
          Waiting on you
          {gate.fields.length > 0 && (
            <span className="font-mono normal-case tracking-normal">
              · {gate.fields.length} question{gate.fields.length === 1 ? "" : "s"}
            </span>
          )}
        </p>
        <h2 className="mt-1 text-[16px] font-semibold leading-snug">{gate.question}</h2>
        <p className="mt-1 text-[12px] text-graphite">
          The pipeline is paused at {gate.stage}. Nothing runs until you answer.
        </p>
      </div>

      {gate.fields.length > 0 && (
        <div className="space-y-4 px-5 py-4">
          {gate.fields.map((f) => (
            <div key={f.id}>
              <label htmlFor={f.id} className="block text-[13px] font-medium">{f.label}</label>
              {f.help && <p className="mt-0.5 text-[12px] text-graphite">{f.help}</p>}
              <textarea
                id={f.id}
                rows={2}
                placeholder={f.placeholder}
                value={answers[f.id] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [f.id]: e.target.value })}
                className="mt-1.5 w-full resize-y border border-rule bg-paper px-3 py-2 text-[13px]"
              />
              {f.placeholder && (
                <div className="mt-1.5 flex items-start gap-2 text-[12px] text-graphite">
                  <p className="min-w-0 flex-1">Leave blank to accept: <span className="text-ink">{f.placeholder}</span></p>
                  <button
                    type="button"
                    onClick={() => setAnswers({ ...answers, [f.id]: f.placeholder ?? "" })}
                    className="shrink-0 rounded border border-rule bg-paper px-2 py-0.5 text-[11px] hover:bg-mist"
                  >
                    Use it
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="px-5 pb-4">
        <label htmlFor="gate-notes" className="block text-[13px] font-medium">
          Anything the agents should know
        </label>
        <textarea
          id="gate-notes"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional. If you send this back, write what to change."
          className="mt-1.5 w-full resize-y border border-rule bg-paper px-3 py-2 text-[13px]"
        />
      </div>

      {error && <p className="px-5 pb-3 text-[13px] text-rust">{error}</p>}

      <div className="flex flex-wrap gap-2 border-t border-ochre/40 px-5 py-4">
        {gate.options.map((opt, i) => (
          <button
            key={opt.value}
            disabled={busy !== null}
            onClick={() => decide(opt.value)}
            className={
              i === 0
                ? "rounded bg-signal px-4 py-2 text-[13px] font-medium text-paper transition-colors hover:bg-[#0054B6] disabled:opacity-50"
                : "rounded border border-rule bg-paper px-4 py-2 text-[13px] transition-colors hover:bg-mist disabled:opacity-50"
            }
          >
            {busy === opt.value ? "Recording…" : opt.label}
          </button>
        ))}
      </div>
    </aside>
  );
}
