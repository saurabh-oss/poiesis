"use client";

import { useState } from "react";
import { api, type RunDetail } from "@/lib/api";
import Icon from "./Icon";

/** Stop a run, or continue one that stopped. Everything already done is kept. */
export default function RunControls({ run, onChange }: { run: RunDetail; onChange: () => Promise<void> | void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const status = run.status;
  const canCancel = status === "running" || status === "scheduled";
  const canRetry = status === "failed" || status === "cancelled";
  if (!canCancel && !canRetry) return null;

  async function act(kind: "cancel" | "retry") {
    setBusy(true);
    setError(null);
    try {
      if (kind === "cancel") await api.cancelRun(run.id);
      else await api.retryRun(run.id);
      setConfirm(false);
      await onChange();
    } catch (e: any) {
      setError(e.message ?? "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded border border-rule bg-paper px-4 py-3 shadow-spectrum">
      {canCancel && !confirm && (
        <button type="button" onClick={() => setConfirm(true)} className="inline-flex items-center gap-1.5 text-[13px] text-graphite hover:text-rust">
          <Icon name="x" size={13} /> Stop this run
        </button>
      )}
      {canCancel && confirm && (
        <div className="space-y-2 text-[13px]">
          <p>Stop where it is? Everything finished so far is kept, and Retry continues from the last checkpoint.</p>
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={() => act("cancel")} className="rounded bg-rust px-3 py-1.5 text-[13px] font-medium text-paper disabled:opacity-50">
              {busy ? "Stopping…" : "Stop the run"}
            </button>
            <button type="button" onClick={() => setConfirm(false)} className="rounded border border-rule px-3 py-1.5 text-[13px]">Keep going</button>
          </div>
        </div>
      )}
      {canRetry && (
        <button type="button" disabled={busy} onClick={() => act("retry")} className="inline-flex items-center gap-1.5 rounded bg-signal px-3.5 py-1.5 text-[13px] font-medium text-paper hover:bg-[#0054B6] disabled:opacity-50">
          <Icon name="arrow" size={13} /> {busy ? "Continuing…" : "Continue from the last checkpoint"}
        </button>
      )}
      {error && <p className="mt-2 text-[12px] text-rust">{error}</p>}
    </section>
  );
}
