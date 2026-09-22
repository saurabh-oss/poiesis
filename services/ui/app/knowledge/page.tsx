"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type KnowledgeStats, type Lesson, type Recall } from "@/lib/api";
import Icon from "@/components/Icon";

function Count({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded border border-rule bg-paper px-3 py-2 text-center shadow-spectrum">
      <p className="font-mono text-[20px] font-semibold tabular-nums">{value ?? "—"}</p>
      <p className="text-[11px] uppercase tracking-[0.06em] text-graphite">{label}</p>
    </div>
  );
}

export default function KnowledgePage() {
  const [caps, setCaps] = useState<any[]>([]);
  const [stack, setStack] = useState<any[]>([]);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [q, setQ] = useState("");
  const [recall, setRecall] = useState<Recall | null>(null);
  const [searching, setSearching] = useState(false);
  const [reindex, setReindex] = useState<string | null>(null);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => setCaps([]));
    api.stack().then(setStack).catch(() => setStack([]));
    api.knowledgeStats().then(setStats).catch(() => setStats(null));
    api.lessons().then(setLessons).catch(() => setLessons([]));
  }, []);

  async function search() {
    if (!q.trim()) return;
    setSearching(true);
    try { setRecall(await api.recall(q)); } catch { setRecall(null); } finally { setSearching(false); }
  }

  async function runReindex() {
    setReindex("starting…");
    try {
      await api.reindex();
      const poll = setInterval(async () => {
        const s = await api.reindexStatus();
        setReindex(s.status + (s.vectors ? ` · ${Object.entries(s.vectors).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""));
        if (s.status !== "running") { clearInterval(poll); api.knowledgeStats().then(setStats).catch(() => undefined); }
      }, 3000);
    } catch (e: any) { setReindex(e.message); }
  }

  const g = stats?.graph ?? {};

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-[28px] font-semibold tracking-[-0.02em]">What the portfolio already knows</h1>
        <p className="mt-2 max-w-[70ch] text-[15px] leading-relaxed text-graphite">
          Every architecture decision is checked against this graph before a line of code is
          written, and every finished run adds what it built, what it decided and what it learned.
          Recall is by word and by meaning.
        </p>
        <div className="mt-5 grid grid-cols-4 gap-2 sm:grid-cols-8">
          <Count label="projects" value={g.projects} />
          <Count label="components" value={g.components} />
          <Count label="capabilities" value={g.capabilities} />
          <Count label="technologies" value={g.technologies} />
          <Count label="decisions" value={g.decisions} />
          <Count label="stories" value={g.stories} />
          <Count label="lessons" value={g.lessons} />
          <Count label="reuse edges" value={g.reuse_edges} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] text-graphite">
          <span>
            Vector index: {stats?.vectors_enabled ? Object.entries(stats.vectors ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "empty" : "off"}
          </span>
          <button type="button" onClick={runReindex} className="rounded border border-rule px-2 py-0.5 hover:border-signal/50 hover:text-signal">
            Re-embed the portfolio
          </button>
          {reindex && <span className="font-mono">{reindex}</span>}
        </div>
      </section>

      <section className="rounded border border-rule bg-paper p-5 shadow-spectrum">
        <form onSubmit={(e) => { e.preventDefault(); void search(); }} className="flex gap-2">
          <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask the graph: duplicate detection, leave overlap, seeding a table a screen reads…"
            className="w-full border border-rule px-3 py-2 text-[14px]" />
          <button type="submit" disabled={searching} className="rounded bg-signal px-4 py-2 text-[13px] font-medium text-paper hover:bg-[#0054B6] disabled:opacity-50">
            {searching ? "…" : "Recall"}
          </button>
        </form>
        {recall && (
          <div className="mt-5 grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-graphite">Components (by word, then by meaning)</h3>
              <ul className="mt-2 divide-y divide-rule">
                {[...recall.graph.map((c) => ({ ...c, via: "word" })), ...recall.components.map((c) => ({ ...c, via: "meaning" }))].slice(0, 12).map((c, i) => (
                  <li key={i} className="py-2 text-[13px]">
                    <span className="font-medium">{c.component}</span> <span className="text-graphite">({c.kind}) · {c.project} · {c.path}</span>
                    <span className="ml-2 rounded border border-rule px-1.5 font-mono text-[10.5px] text-graphite">{c.via}{c.score ? ` ${c.score}` : ""}</span>
                    {c.purpose && <p className="text-[12px] text-graphite">{c.purpose}</p>}
                  </li>
                ))}
                {!recall.graph.length && !recall.components.length && <li className="py-2 text-[13px] text-graphite">Nothing matched.</li>}
              </ul>
            </div>
            <div className="space-y-5">
              <div>
                <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-graphite">Past stories</h3>
                <ul className="mt-2 divide-y divide-rule">
                  {recall.stories.map((s, i) => (
                    <li key={i} className="py-2 text-[13px]">
                      <Link href={`/runs/${s.run_id}`} className="font-medium hover:text-signal">{s.title}</Link>
                      <span className="text-graphite"> · {s.project} · {s.outcome}</span>
                    </li>
                  ))}
                  {!recall.stories.length && <li className="py-2 text-[13px] text-graphite">No past story resembles this.</li>}
                </ul>
              </div>
              <div>
                <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-graphite">Lessons that apply</h3>
                <ul className="mt-2 divide-y divide-rule">
                  {recall.lessons.map((l, i) => <li key={i} className="py-2 text-[13px]">{l.lesson}</li>)}
                  {!recall.lessons.length && <li className="py-2 text-[13px] text-graphite">None yet.</li>}
                </ul>
              </div>
              <div>
                <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] text-graphite">Decisions</h3>
                <ul className="mt-2 divide-y divide-rule">
                  {recall.decisions.map((d, i) => <li key={i} className="py-2 text-[13px]"><span className="font-medium">{d.title}</span> <span className="text-graphite">— {d.decision}</span></li>)}
                  {!recall.decisions.length && <li className="py-2 text-[13px] text-graphite">None recorded.</li>}
                </ul>
              </div>
            </div>
          </div>
        )}
      </section>

      <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section>
          <h2 className="text-[15px] font-semibold">Lessons the platform has learned</h2>
          <p className="mt-1 text-[13px] text-graphite">
            Each one came from a story that failed or needed repairs. The Developer is shown the ones that apply before it writes a similar story.
          </p>
          {lessons.length === 0 ? (
            <p className="mt-4 text-[13px] text-graphite">Nothing yet: lessons are recorded when a run finishes.</p>
          ) : (
            <ul className="mt-4 divide-y divide-rule border-y border-rule">
              {lessons.map((l) => (
                <li key={l.id} className="py-3">
                  <p className="text-[14px]">{l.lesson}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-graphite">
                    {l.applies_to} · <Link href={`/runs/${l.run_id}`} className="hover:text-signal">{l.project ?? l.run_id}</Link> · {l.story_id}
                  </p>
                </li>
              ))}
            </ul>
          )}

          <h2 className="mt-10 text-[15px] font-semibold">Capabilities</h2>
          {caps.length === 0 ? (
            <p className="mt-3 text-[13px] text-graphite">
              The graph is empty. Run the indexer to load your repositories:
              <code className="ml-1 font-mono text-[12.5px]">docker compose run --rm indexer</code>
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-rule border-y border-rule">
              {caps.map((c) => (
                <li key={c.capability} className="flex flex-wrap items-baseline gap-3 py-2.5">
                  <span className="text-[14px]">{c.capability}</span>
                  <span className="font-mono text-[12px] text-graphite">{c.projects.join(" · ")}</span>
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
          <a href="http://localhost:7474" target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-[12px] text-signal hover:underline">
            Open the graph in Neo4j <Icon name="external" size={11} />
          </a>
        </aside>
      </div>
    </div>
  );
}
