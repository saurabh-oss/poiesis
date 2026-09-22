"use client";

import { useEffect, useState } from "react";
import { api, type Integrations } from "@/lib/api";
import Icon from "./Icon";

function Row({ label, href, text }: { label: string; href?: string; text: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className="text-[12px] text-graphite">{label}</span>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 truncate font-mono text-[12px] text-signal hover:underline">
          {text} <Icon name="external" size={11} />
        </a>
      ) : (
        <span className="truncate font-mono text-[12px]">{text}</span>
      )}
    </div>
  );
}

export default function IntegrationsCard({ runId, active }: { runId: string; active: boolean }) {
  const [data, setData] = useState<Integrations | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.integrations(runId).then((d) => { if (alive) setData(d); }).catch(() => undefined);
    load();
    const timer = active ? setInterval(load, 15000) : null;
    return () => { alive = false; if (timer) clearInterval(timer); };
  }, [runId, active]);

  if (!data) return null;
  const jira = data.jira ?? {};
  const git = data.git ?? {};
  const jiraOn = Boolean(jira.configured ?? jira.enabled);
  const gitOn = Boolean(git.configured);
  if (!jiraOn && !gitOn) return null;

  const stories = Object.entries(jira.stories ?? {}) as [string, { key?: string; url?: string }][];

  return (
    <section className="rounded border border-rule bg-paper shadow-spectrum">
      <div className="border-b border-rule px-4 py-2.5">
        <h2 className="text-[13px] font-medium">Where this run lives</h2>
      </div>
      <div className="divide-y divide-rule px-4 py-1 text-[13px]">
        {gitOn && (
          <div className="py-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-graphite">Git</p>
            {git.url ? (
              <>
                <Row label="Repository" href={git.url} text={git.url.replace(/^https?:\/\//, "")} />
                {git.branch && <Row label="Branch" href={`${git.url}/tree/${git.branch}`} text={git.branch} />}
                {git.release?.tag && <Row label="Tag" text={git.release.tag} />}
                {git.pull_request?.url && <Row label="Pull request" href={git.pull_request.url} text={`#${git.pull_request.number}`} />}
                {git.release?.default_branch && <Row label="Default branch" text={`${git.release.default_branch} updated`} />}
              </>
            ) : (
              <p className="py-1 text-[12px] text-graphite">Pushed once the scaffold is laid down.</p>
            )}
          </div>
        )}
        {jiraOn && (
          <div className="py-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-graphite">Jira</p>
            {jira.initiative?.url ? (
              <>
                <Row label="Initiative" href={jira.initiative.url} text={jira.initiative.key ?? ""} />
                {jira.sprint?.name && <Row label="Sprint" text={jira.sprint.name} />}
                {stories.length > 0 && (
                  <div className="flex flex-wrap gap-1 py-1.5">
                    {stories.map(([sid, s]) => (
                      <a key={sid} href={s.url} target="_blank" rel="noreferrer" className="rounded border border-rule px-1.5 py-0.5 font-mono text-[11px] text-signal hover:border-signal/50">
                        {sid} → {s.key}
                      </a>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="py-1 text-[12px] text-graphite">Mirrored once the backlog is approved.</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
