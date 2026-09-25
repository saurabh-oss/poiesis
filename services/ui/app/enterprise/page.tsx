"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Connector, type EnterpriseCatalogue } from "@/lib/api";
import Icon from "@/components/Icon";

const LOGO: Record<string, string> = {
  jira: "linear-gradient(135deg,#2684FF,#0052CC)",
  servicenow: "linear-gradient(135deg,#62D84E,#1F8476)",
  plane: "linear-gradient(135deg,#3F76FF,#1A3F99)",
  email: "linear-gradient(135deg,#E68619,#B35F00)",
  slack: "linear-gradient(135deg,#E01E5A,#611F69)",
  teams: "linear-gradient(135deg,#7B83EB,#4B53BC)",
};

const MODE = {
  live: { label: "Live for apps", cls: "bg-[#E6F6EF] text-[#007A4D]" },
  sandbox: { label: "Sandbox", cls: "bg-[#F5F9FF] text-signal" },
  off: { label: "Off", cls: "bg-mist text-graphite" },
} as const;

function ConnectorCard({ c, index }: { c: Connector; index: number }) {
  const [open, setOpen] = useState(false);
  const mode = MODE[c.mode] ?? MODE.sandbox;
  return (
    <article className="enter flex flex-col rounded-xl border border-rule bg-paper shadow-spectrum transition hover:-translate-y-0.5 hover:shadow-lg"
             style={{ animationDelay: `${Math.min(index * 60, 600)}ms` }}>
      <div className="flex items-start gap-3 p-4">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-[18px] font-extrabold text-white shadow"
              style={{ background: LOGO[c.name] ?? "#0265DC" }}>{c.title.slice(0, 1)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-[15.5px] font-semibold">{c.title}</h3>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${mode.cls}`}>{mode.label}</span>
          </div>
          <p className="text-[12px] text-graphite">{c.category} · {c.lines} lines · <span className="font-mono">{c.source.split("/").pop()}</span></p>
        </div>
      </div>
      <p className="px-4 text-[13.5px] leading-relaxed text-ink">{c.description}</p>
      <ul className="mt-3 flex flex-wrap gap-1.5 px-4">
        {Object.keys(c.operations).map((op) => (
          <li key={op} title={c.operations[op]} className="rounded-md border border-rule bg-mist px-2 py-0.5 font-mono text-[11.5px]">{op}</li>
        ))}
      </ul>
      <div className="mt-auto px-4 pb-4 pt-3">
        <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-signal hover:underline">
          {open ? "Hide settings" : "Settings to go live"} <Icon name="arrow" size={12} />
        </button>
        {open && (
          <table className="mt-2 w-full text-left text-[12px]">
            <tbody>
              {c.settings.map((s) => (
                <tr key={s.env} className="border-t border-rule align-top">
                  <td className="py-1.5 pr-2 font-mono text-[11px]">APPS_{s.env}</td>
                  <td className="py-1.5 text-graphite">
                    {s.label}{s.required ? " · required" : ""}{s.help ? <span className="block text-[11px]">{s.help}</span> : null}
                  </td>
                  <td className="py-1.5 pl-2 text-right">{s.set ? <span className="text-[#007A4D]">set</span> : <span className="text-graphite">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </article>
  );
}

export default function EnterprisePage() {
  const [data, setData] = useState<EnterpriseCatalogue | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.enterprise().then(setData).catch((e) => setError(String(e.message || e)));
  }, []);

  const groups = data ? Array.from(new Set(data.connectors.map((c) => c.category))) : [];
  return (
    <div className="space-y-8">
      <section className="enter relative overflow-hidden rounded-2xl border border-rule bg-gradient-to-br from-[#0A2D6B] via-[#0265DC] to-[#5258E4] p-7 text-white shadow-spectrum">
        <span aria-hidden className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-3xl" />
        <p className="text-[12px] font-semibold uppercase tracking-[.12em] text-white/70">Enterprise pack</p>
        <h1 className="mt-1 max-w-3xl text-[28px] font-semibold leading-tight">Applications an organisation can run its work on</h1>
        <p className="mt-2 max-w-3xl text-[14.5px] leading-relaxed text-white/85">
          Every app built with <span className="font-mono">packs/enterprise.yaml</span> gets a platform-owned kernel — sign-in and roles,
          server-enforced workflows with approvals and SLAs, an audit trail, a tested rule catalogue — and these connectors. The
          business logic itself is designed once per app, from the whole brief, with a test for every rule.
        </p>
        {data && (
          <div className="mt-5 flex flex-wrap gap-6">
            {[[data.connectors.length, "connectors"], [data.kernel.length, "kernel capabilities"], [data.apps.length, "enterprise apps"],
              [data.connectors.filter((c) => c.mode === "live").length, "live for apps"]].map(([n, l]) => (
              <div key={String(l)}><p className="text-[26px] font-semibold leading-none">{n}</p><p className="text-[12px] text-white/75">{l}</p></div>
            ))}
          </div>
        )}
      </section>

      {error && <p className="rounded-lg border border-[#FFD0CC] bg-[#FFEBE9] p-3 text-[13px] text-[#D31510]">{error}</p>}
      {!data && !error && <p className="text-graphite">Loading…</p>}

      {data && (
        <>
          <section>
            <h2 className="mb-3 text-[17px] font-semibold">What every enterprise app carries</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.kernel.map((k, i) => (
                <div key={k.key} className="enter rounded-xl border border-rule bg-paper p-4 shadow-spectrum" style={{ animationDelay: `${i * 50}ms` }}>
                  <p className="text-[14.5px] font-semibold">{k.title}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-graphite">{k.detail}</p>
                </div>
              ))}
            </div>
          </section>

          {groups.map((g) => (
            <section key={g}>
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-[17px] font-semibold">{g} connectors</h2>
                <p className="text-[12px] text-graphite">Sandbox until credentials are set; the same call then goes live</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {data.connectors.filter((c) => c.category === g).map((c, i) => <ConnectorCard key={c.name} c={c} index={i} />)}
              </div>
            </section>
          ))}

          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-rule bg-paper p-5 shadow-spectrum">
              <h2 className="text-[16px] font-semibold">Using one in a story</h2>
              <pre className="mt-3 overflow-x-auto rounded-lg bg-[#0D1321] p-4 font-mono text-[12px] leading-relaxed text-[#D8E2F5]">{`from ..connectors import jira, teams

r = jira().create_issue(
    "Checkout fails for EU cards", "14 reports since 09:10",
    labels=["known-issue"], idempotency_key=f"issue-{issue.id}")
if r.ok:
    issue.jira_key = r.key          # SUP-104, sandbox or live
teams().post("Known issue raised", r.key,
             facts={"Reports": 14}, link=("Open", r.url))`}</pre>
            </div>
            <div className="rounded-xl border border-rule bg-paper p-5 shadow-spectrum">
              <h2 className="text-[16px] font-semibold">Making them live for every app</h2>
              <p className="mt-2 text-[13px] leading-relaxed text-graphite">
                Set the settings in the platform&apos;s <span className="font-mono">.env</span> with an <span className="font-mono">APPS_</span> prefix
                (<span className="font-mono">APPS_JIRA_BASE_URL</span>, <span className="font-mono">APPS_SMTP_HOST</span>…). Each deployment writes them into the
                app&apos;s <span className="font-mono">app.env</span>, which is never committed. Without them every connector runs in its sandbox: calls are kept in the
                app&apos;s outbox and its Integrations screen shows what would have been sent.
              </p>
              <p className="mt-3 text-[12.5px] text-graphite">
                Live settings present: {data.live_settings.length ? data.live_settings.map((s) => <span key={s} className="mr-1 font-mono">{s}</span>) : "none"}
              </p>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-[17px] font-semibold">Enterprise apps</h2>
            {data.apps.length === 0 ? (
              <p className="rounded-xl border border-dashed border-rule p-6 text-[13.5px] text-graphite">
                None yet. Set <span className="font-mono">POIESIS_PACK=packs/enterprise.yaml</span> and submit a brief.
              </p>
            ) : (
              <div className="overflow-hidden rounded-xl border border-rule bg-paper shadow-spectrum">
                <table className="w-full text-left text-[13px]">
                  <thead className="bg-mist text-[11px] uppercase tracking-wider text-graphite">
                    <tr><th className="px-4 py-2.5">App</th><th>Rules</th><th>Workflows</th><th>Roles</th><th>Rule tests</th><th>Status</th><th className="pr-4" /></tr>
                  </thead>
                  <tbody>
                    {data.apps.map((a) => (
                      <tr key={a.run_id} className="border-t border-rule">
                        <td className="px-4 py-3"><Link href={`/runs/${a.run_id}`} className="font-medium hover:text-signal">{a.title}</Link>
                          <span className="block font-mono text-[11px] text-graphite">{a.run_id.slice(0, 8)}</span></td>
                        <td>{a.rules}</td><td>{a.workflows}</td><td>{a.roles}</td>
                        <td>{a.tests.total ? <span className={a.tests.failed ? "text-[#D31510]" : "text-[#007A4D]"}>{a.tests.passed}/{a.tests.total}</span> : "—"}</td>
                        <td>{a.status}</td>
                        <td className="pr-4 text-right">{a.url && <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-signal hover:underline">Open <Icon name="external" size={12} /></a>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
