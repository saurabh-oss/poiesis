"use client";

import { useEffect, useState } from "react";
import { api, type Deployment } from "@/lib/api";

const tone: Record<string, string> = {
  running: "border-moss text-moss",
  starting: "border-signal text-signal",
  failed: "border-rust text-rust",
  stopped: "border-rule text-graphite",
};

export default function DeploymentCard({
  runId, deployment, canDeploy, onChange,
}: {
  runId: string;
  deployment: Deployment | null;
  canDeploy: boolean;
  onChange: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<"deploy" | "stop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = deployment?.status ?? "none";

  // A first start builds three images; keep the card current until it settles.
  useEffect(() => {
    if (status !== "starting") return;
    const timer = setInterval(() => { void onChange(); }, 4000);
    return () => clearInterval(timer);
  }, [status, onChange]);

  async function act(kind: "deploy" | "stop") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "deploy") await api.deploy(runId);
      else await api.stopDeployment(runId);
      await onChange();
    } catch (e: any) {
      setError(e.message ?? "That did not work. Try again.");
    } finally {
      setBusy(null);
    }
  }

  if (!deployment && !canDeploy) return null;

  return (
    <section className="rounded border border-rule bg-paper shadow-spectrum">
      <div className="flex items-center justify-between border-b border-rule px-4 py-2.5">
        <h2 className="text-[13px] font-medium">Running application</h2>
        {deployment && (
          <span className={`rounded border px-2 py-0.5 font-mono text-[11px] ${tone[status] ?? tone.stopped}`}>
            {status}
          </span>
        )}
      </div>

      <div className="space-y-3 px-4 py-4 text-[13px]">
        {status === "running" && deployment && (
          <>
            <a
              href={deployment.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded bg-signal px-4 py-2.5 text-center text-[14px] font-medium text-paper transition-colors hover:bg-[#0054B6]"
            >
              Open the app ↗
            </a>
            <p className="break-all font-mono text-[12px] text-graphite">{deployment.url}</p>
          </>
        )}
        {status === "starting" && (
          <p className="text-graphite">
            Building images and waiting for every service to report healthy. A first
            start takes a few minutes.
          </p>
        )}
        {status === "failed" && deployment && (
          <pre className="tape max-h-[180px] overflow-auto whitespace-pre-wrap rounded bg-mist p-2 font-mono text-[11px] text-rust">
            {deployment.detail || "It did not start."}
          </pre>
        )}
        {status === "stopped" && (
          <p className="text-graphite">
            Stopped. Its data is kept, and starting it again reuses the same address
            when that port is still free.
          </p>
        )}
        {status === "none" && (
          <p className="text-graphite">This increment has not been started yet.</p>
        )}

        {error && <p className="text-rust">{error}</p>}

        <div className="flex flex-wrap gap-2">
          {status !== "starting" && (
            <button
              onClick={() => act("deploy")}
              disabled={busy !== null}
              className="rounded border border-rule bg-paper px-3 py-1.5 text-[13px] transition-colors hover:bg-mist disabled:opacity-50"
            >
              {busy === "deploy" ? "Starting…"
                : status === "running" ? "Redeploy"
                : status === "none" ? "Start the app" : "Start again"}
            </button>
          )}
          {(status === "running" || status === "failed") && (
            <button
              onClick={() => act("stop")}
              disabled={busy !== null}
              className="rounded border border-rule bg-paper px-3 py-1.5 text-[13px] transition-colors hover:bg-mist disabled:opacity-50"
            >
              {busy === "stop" ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
