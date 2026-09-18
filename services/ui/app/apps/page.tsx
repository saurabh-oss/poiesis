"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type Deployment } from "@/lib/api";

const tone: Record<string, string> = {
  running: "border-moss text-moss",
  starting: "border-signal text-signal",
  failed: "border-rust text-rust",
  stopped: "border-rule text-graphite",
};

export default function AppsPage() {
  const [apps, setApps] = useState<Deployment[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setApps(await api.deployments());
      setError(null);
    } catch {
      setError("The orchestrator is not answering on port 8080. Check that it is running.");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 8000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function act(runId: string, kind: "deploy" | "stop") {
    setBusy(`${runId}:${kind}`);
    try {
      if (kind === "deploy") await api.deploy(runId);
      else await api.stopDeployment(runId);
      await refresh();
    } catch (e: any) {
      setError(e.message ?? "That did not work. Try again.");
    } finally {
      setBusy(null);
    }
  }

  const running = apps.filter((a) => a.status === "running").length;

  return (
    <div>
      <h1 className="text-[28px] font-semibold tracking-[-0.02em]">Running applications</h1>
      <p className="mt-2 max-w-[64ch] text-[15px] leading-relaxed text-graphite">
        Every run starts its application before the release decision, so you can try it
        before you approve it. {running > 0 && `${running} running now.`}
      </p>

      {error && <p className="mt-4 text-[13px] text-rust">{error}</p>}

      {loaded && apps.length === 0 ? (
        <p className="mt-8 max-w-[64ch] text-[14px] text-graphite">
          Nothing has been started yet. New runs start their application automatically;
          a run that finished before this existed can be started from its run page.
        </p>
      ) : (
        <div className="mt-8 overflow-x-auto rounded border border-rule bg-paper shadow-spectrum">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-rule bg-mist text-left text-graphite">
                <th className="px-4 py-2.5 font-medium">Application</th>
                <th className="px-4 py-2.5 font-medium">Address</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Started</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {apps.map((a) => (
                <tr key={a.run_id} className="border-b border-rule/70 align-top last:border-b-0">
                  <td className="px-4 py-3">
                    <Link href={`/runs/${a.run_id}`} className="font-medium hover:text-signal">
                      {a.title || a.run_id}
                    </Link>
                    <p className="font-mono text-[11px] text-graphite">{a.project}</p>
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px]">
                    {a.status === "running" && a.url ? (
                      <a href={a.url} target="_blank" rel="noreferrer" className="text-signal underline">
                        {a.url}
                      </a>
                    ) : (
                      <span className="text-graphite">{a.url || "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded border px-2 py-0.5 font-mono text-[11px] ${tone[a.status] ?? tone.stopped}`}>
                      {a.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px] text-graphite">
                    {a.started_at ? new Date(a.started_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {a.status !== "starting" && (
                        <button
                          onClick={() => act(a.run_id, "deploy")}
                          disabled={busy !== null}
                          className="rounded border border-rule bg-paper px-3 py-1 text-[12px] hover:bg-mist disabled:opacity-50"
                        >
                          {busy === `${a.run_id}:deploy` ? "Starting…" : a.status === "running" ? "Redeploy" : "Start"}
                        </button>
                      )}
                      {(a.status === "running" || a.status === "failed") && (
                        <button
                          onClick={() => act(a.run_id, "stop")}
                          disabled={busy !== null}
                          className="rounded border border-rule bg-paper px-3 py-1 text-[12px] hover:bg-mist disabled:opacity-50"
                        >
                          {busy === `${a.run_id}:stop` ? "Stopping…" : "Stop"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
