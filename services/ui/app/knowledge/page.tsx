"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type KnowledgeStats, type Lesson, type Recall } from "@/lib/api";
import Icon from "@/components/Icon";
import { CountUp, PALETTE, colorFor as hashColor } from "@/components/charts";

const TILES: { key: string; label: string; icon: string; color: string; note: string }[] = [
  { key: "projects", label: "Projects", icon: "release", color: "#0265DC", note: "repositories and generated apps" },
  { key: "components", label: "Components", icon: "build", color: "#4046CA", note: "modules, services, screens" },
  { key: "capabilities", label: "Capabilities", icon: "spark", color: "#0FB5AE", note: "what they can do" },
  { key: "technologies", label: "Technologies", icon: "wrench", color: "#F68511", note: "the house stack" },
  { key: "decisions", label: "Decisions", icon: "architecture", color: "#7326D3", note: "architecture choices kept" },
  { key: "stories", label: "Stories", icon: "backlog", color: "#DE3D82", note: "built and remembered" },
  { key: "lessons", label: "Lessons", icon: "flask", color: "#E68619", note: "from failures and repairs" },
  { key: "reuse_edges", label: "Reuse links", icon: "link", color: "#147AF3", note: "where work was reused" },
];

type Tab = "projects" | "lessons" | "stack";

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-graphite">
        {title}<span className="rounded-full bg-mist px-1.5 font-mono text-[10.5px]">{count}</span>
      </h3>
      {children}
    </div>
  );
}

function Score({ value }: { value?: number }) {
  if (value === undefined || value === null) return null;
  const pct = Math.max(4, Math.min(100, value <= 1 ? value * 100 : value));
  return (
    <span className="inline-flex items-center gap-1" title={`match ${value}`}>
      <span className="h-1 w-10 overflow-hidden rounded-full bg-mist"><span className="block h-full rounded-full bg-signal" style={{ width: `${pct}%` }} /></span>
    </span>
  );
}

export default function KnowledgePage() {
  const [caps, setCaps] = useState<{ capability: string; projects: string[] }[]>([]);
  const [stack, setStack] = useState<{ technology: string; category?: string | null; projects: number }[]>([]);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [recall, setRecall] = useState<Recall | null>(null);
  const [asked, setAsked] = useState("");
  const [searching, setSearching] = useState(false);
  const [reindex, setReindex] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("projects");
  const [filter, setFilter] = useState("");
  const [project, setProject] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.capabilities().then(setCaps).catch(() => setCaps([])),
      api.stack().then(setStack).catch(() => setStack([])),
      api.knowledgeStats().then(setStats).catch(() => setStats(null)),
      api.lessons().then(setLessons).catch(() => setLessons([])),
    ]).finally(() => setLoaded(true));
  }, []);

  async function search(text?: string) {
    const query = (text ?? q).trim();
    if (!query) return;
    setQ(query);
    setSearching(true);
    try { setRecall(await api.recall(query)); setAsked(query); } catch { setRecall(null); } finally { setSearching(false); }
  }

  async function runReindex() {
    setReindex("starting…");
    try {
      await api.reindex();
      const poll = setInterval(async () => {
        const s = await api.reindexStatus();
        setReindex(s.status);
        if (s.status !== "running") { clearInterval(poll); api.knowledgeStats().then(setStats).catch(() => undefined); }
      }, 3000);
    } catch (e: any) { setReindex(e.message); }
  }

  const projects = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const c of caps) for (const p of c.projects) m.set(p, [...(m.get(p) ?? []), c.capability]);
    return [...m.entries()].map(([name, list]) => ({ name, caps: list.sort((a, b) => a.localeCompare(b)) }))
      .sort((a, b) => b.caps.length - a.caps.length || a.name.localeCompare(b.name));
  }, [caps]);
  const maxCaps = Math.max(...projects.map((p) => p.caps.length), 1);
  // Projects get distinct colours by rank; anything else falls back to a stable hash.
  const projectColor = useMemo(() => new Map(projects.map((p, i) => [p.name, PALETTE[i % PALETTE.length]])), [projects]);
  const colorFor = (key: string) => projectColor.get(key) ?? hashColor(key);
  const f = filter.trim().toLowerCase();
  const shownProjects = projects.filter((p) => (!project || p.name === project)
    && (!f || p.name.toLowerCase().includes(f) || p.caps.some((c) => c.toLowerCase().includes(f))));
  const lessonProjects = [...new Set(lessons.map((l) => l.project ?? l.run_id))];
  const shownLessons = lessons.filter((l) => (!project || (l.project ?? l.run_id) === project)
    && (!f || l.lesson.toLowerCase().includes(f) || l.applies_to.toLowerCase().includes(f)));
  const shownStack = stack.filter((t) => !f || t.technology.toLowerCase().includes(f));
  const maxStack = Math.max(...stack.map((t) => t.projects), 1);
  const suggestions = [...new Set(caps.map((c) => c.capability).filter((c) => /[a-z] [a-z]/i.test(c)))].slice(0, 4);
  const g = stats?.graph ?? {};
  const vectors = stats?.vectors_enabled ? Object.values(stats.vectors ?? {}).reduce((a, b) => a + (b as number), 0) : 0;

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "projects", label: "Projects & capabilities", count: projects.length },
    { key: "lessons", label: "Lessons learned", count: lessons.length },
    { key: "stack", label: "House stack", count: stack.length },
  ];

  return (
    <div className="space-y-7">
      <section className="grid items-stretch gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,560px)]">
        <div className="enter flex flex-col">
          <h1 className="text-[28px] font-semibold tracking-[-0.02em] xl:text-[34px]">What the portfolio already knows</h1>
          <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-graphite">
            Every architecture decision is checked against this graph before a line of code is written, and every
            finished run adds what it built, what it decided and what it learned. Agents recall it by word and by meaning.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-[12px] lg:mt-auto lg:pt-4">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${stats?.vectors_enabled ? "bg-moss/10 text-moss" : "bg-mist text-graphite"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${stats?.vectors_enabled ? "bg-moss" : "bg-rule"}`} />
              {stats?.vectors_enabled ? `Meaning search on · ${vectors.toLocaleString()} vectors` : "Meaning search off"}
            </span>
            <button type="button" onClick={runReindex}
                    className="inline-flex items-center gap-1.5 rounded-full border border-rule bg-paper px-2.5 py-1 hover:border-signal/50 hover:text-signal">
              {reindex === "running" || reindex === "starting…" ? <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-signal border-t-transparent" /> : <Icon name="spark" size={11} />}
              {reindex ? `Re-embedding: ${reindex}` : "Re-embed the portfolio"}
            </button>
            <a href="http://localhost:7474" target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 rounded-full border border-rule bg-paper px-2.5 py-1 hover:border-signal/50 hover:text-signal">
              Graph in Neo4j <Icon name="external" size={11} />
            </a>
          </div>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); void search(); }}
              className="enter relative overflow-hidden rounded-xl border border-rule bg-paper p-5 shadow-spectrum" style={{ animationDelay: "80ms" }}>
          <span aria-hidden className="pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full bg-gradient-to-br from-[#0265DC]/15 to-[#EB1000]/10 blur-2xl" />
          <p className="flex items-center gap-2 text-[14px] font-semibold"><Icon name="discovery" size={15} className="text-signal" /> Ask the portfolio</p>
          <p className="mt-0.5 text-[12.5px] text-graphite">The same recall the Architect and Developer use before they design or write.</p>
          <div className="mt-3 flex gap-2">
            <div className="relative flex-1">
              <Icon name="discovery" size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-graphite" />
              <input type="text" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Ask the portfolio"
                     placeholder="duplicate detection, leave overlap, seeding a table…"
                     className="w-full rounded-full border border-rule py-2 pl-9 pr-3 text-[14px] outline-none transition focus:border-signal focus:ring-2 focus:ring-signal/20" />
            </div>
            <button type="submit" disabled={searching || !q.trim()}
                    className="inline-flex items-center gap-1.5 rounded-full bg-signal px-5 py-2 text-[13px] font-medium text-paper shadow-spectrum hover:bg-[#0054B6] disabled:opacity-50">
              {searching ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" /> : null}
              Recall
            </button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px]">
            <span className="text-graphite">Try</span>
            {["duplicate detection", "leave overlap", ...suggestions.slice(0, 2)].map((s) => (
              <button key={s} type="button" onClick={() => void search(s)}
                      className="rounded-full border border-rule px-2.5 py-0.5 text-graphite transition hover:border-signal/50 hover:text-signal">{s}</button>
            ))}
          </div>
        </form>
      </section>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
        {TILES.map((t, i) => (
          <div key={t.key} className="enter spot group relative overflow-hidden rounded-xl border border-rule bg-paper p-3.5 shadow-spectrum transition hover:-translate-y-0.5"
               style={{ animationDelay: `${120 + i * 40}ms` }} title={t.note}>
            <span className="grid h-8 w-8 place-items-center rounded-lg text-white transition group-hover:scale-110"
                  style={{ background: `linear-gradient(135deg, ${t.color}, ${t.color}bb)`, boxShadow: `0 6px 14px -8px ${t.color}` }}>
              <Icon name={t.icon} size={15} />
            </span>
            <p className="mt-2.5 text-[24px] font-semibold leading-none tabular-nums">
              {g[t.key] !== undefined ? <CountUp value={g[t.key]} /> : "—"}
            </p>
            <p className="mt-1 text-[12px] text-graphite">{t.label}</p>
          </div>
        ))}
      </section>

      {recall && (
        <section className="enter rounded-xl border border-signal/25 bg-[#F8FBFF] p-5 shadow-spectrum">
          <div className="mb-4 flex items-center gap-2">
            <p className="text-[14px] font-semibold">What the portfolio recalls for “{asked}”</p>
            <button type="button" onClick={() => setRecall(null)} className="ml-auto rounded-full p-1 text-graphite hover:bg-paper" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Section title="Components" count={recall.graph.length + recall.components.length}>
              <ul className="space-y-2">
                {[...recall.graph.map((c) => ({ ...c, via: "word" })), ...recall.components.map((c) => ({ ...c, via: "meaning" }))].slice(0, 10).map((c, i) => (
                  <li key={i} className="rounded-lg border border-rule bg-paper px-3 py-2">
                    <div className="flex items-center gap-2 text-[13px]">
                      <span className="font-medium">{c.component}</span>
                      <span className="rounded-full px-1.5 text-[10.5px]" style={{ color: colorFor(c.project ?? ""), background: `${colorFor(c.project ?? "")}18` }}>{c.project}</span>
                      <span className={`ml-auto rounded-full px-1.5 text-[10.5px] ${c.via === "word" ? "bg-mist text-graphite" : "bg-[#F5F9FF] text-signal"}`}>by {c.via}</span>
                      <Score value={c.score} />
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[11px] text-graphite">{c.kind} · {c.path}</p>
                    {c.purpose && <p className="mt-0.5 text-[12px] text-graphite">{c.purpose}</p>}
                  </li>
                ))}
                {!recall.graph.length && !recall.components.length && <li className="text-[13px] text-graphite">Nothing matched.</li>}
              </ul>
            </Section>
            <div className="space-y-5">
              <Section title="Past stories" count={recall.stories.length}>
                <ul className="space-y-1.5">
                  {recall.stories.map((s, i) => (
                    <li key={i} className="flex items-center gap-2 rounded-lg border border-rule bg-paper px-3 py-2 text-[13px]">
                      <Link href={`/runs/${s.run_id}`} className="min-w-0 truncate font-medium hover:text-signal">{s.title}</Link>
                      <span className="shrink-0 text-[11.5px] text-graphite">{s.project}</span>
                      <span className={`ml-auto shrink-0 rounded-full px-1.5 text-[10.5px] ${/^green/.test(s.outcome) ? "bg-moss/10 text-moss" : /^red/.test(s.outcome) ? "bg-rust/10 text-rust" : "bg-mist text-graphite"}`}>{s.outcome}</span>
                    </li>
                  ))}
                  {!recall.stories.length && <li className="text-[13px] text-graphite">No past story resembles this.</li>}
                </ul>
              </Section>
              <Section title="Lessons that apply" count={recall.lessons.length}>
                <ul className="space-y-1.5">
                  {recall.lessons.map((l, i) => <li key={i} className="rounded-lg border-l-2 border-[#E68619] bg-paper px-3 py-2 text-[12.5px]">{l.lesson}</li>)}
                  {!recall.lessons.length && <li className="text-[13px] text-graphite">None yet.</li>}
                </ul>
              </Section>
              <Section title="Decisions" count={recall.decisions.length}>
                <ul className="space-y-1.5">
                  {recall.decisions.map((d, i) => (
                    <li key={i} className="rounded-lg border-l-2 border-[#7326D3] bg-paper px-3 py-2 text-[12.5px]">
                      <span className="font-medium">{d.title}</span> <span className="text-graphite">— {d.decision}</span>
                    </li>
                  ))}
                  {!recall.decisions.length && <li className="text-[13px] text-graphite">None recorded.</li>}
                </ul>
              </Section>
            </div>
          </div>
        </section>
      )}

      <section className="enter space-y-4" style={{ animationDelay: "300ms" }}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap gap-1 rounded-full border border-rule bg-mist p-1 text-[13px]">
            {tabs.map((t) => (
              <button key={t.key} onClick={() => { setTab(t.key); setProject(null); }}
                      className={`rounded-full px-3.5 py-1.5 transition ${tab === t.key ? "bg-paper font-medium text-ink shadow-spectrum" : "text-graphite hover:text-ink"}`}>
                {t.label}<span className="ml-1.5 font-mono text-[11px] text-graphite">{t.count}</span>
              </button>
            ))}
          </div>
          <div className="relative ml-auto w-full sm:w-[280px]">
            <Icon name="discovery" size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-graphite" />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter"
                   placeholder={tab === "projects" ? "Filter projects and capabilities" : tab === "lessons" ? "Filter lessons" : "Filter technologies"}
                   className="w-full rounded-full border border-rule bg-paper py-1.5 pl-8 pr-3 text-[13px] outline-none focus:border-signal focus:ring-2 focus:ring-signal/20" />
          </div>
        </div>

        {!loaded ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-[160px] rounded-xl" />)}</div>
        ) : tab === "projects" ? (
          caps.length === 0 ? (
            <p className="text-[13px] text-graphite">
              The graph is empty. Run the indexer to load your repositories: <code className="font-mono text-[12.5px]">docker compose run --rm indexer</code>
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-2 rounded-xl border border-rule bg-paper p-4 shadow-spectrum" aria-label="Projects by number of capabilities">
                {projects.map((p, i) => {
                  const size = 26 + Math.sqrt(p.caps.length / maxCaps) * 46;
                  const on = project === p.name;
                  return (
                    <button key={p.name} type="button" onClick={() => setProject(on ? null : p.name)} title={`${p.name}: ${p.caps.length} capabilities`}
                            className={`bubble-in grid place-items-center rounded-full font-semibold text-white transition hover:scale-110 ${project && !on ? "opacity-30" : ""}`}
                            style={{ width: size, height: size, fontSize: Math.max(9, size / 4.6), background: `radial-gradient(circle at 30% 30%, ${colorFor(p.name)}, ${colorFor(p.name)}cc)`,
                                     boxShadow: on ? `0 0 0 3px #fff, 0 0 0 5px ${colorFor(p.name)}` : `0 6px 14px -8px ${colorFor(p.name)}`, animationDelay: `${i * 35}ms` }}>
                      {p.caps.length}
                    </button>
                  );
                })}
                <p className="ml-auto self-center text-[12px] text-graphite">
                  {project ? <>Showing <b className="text-ink">{project}</b> · <button className="text-signal hover:underline" onClick={() => setProject(null)}>show all</button></>
                    : "Each bubble is a project, sized by what it can do. Click one to focus it."}
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {shownProjects.map((p, i) => (
                  <article key={p.name} className="enter spot rounded-xl border border-rule bg-paper p-4 shadow-spectrum transition hover:-translate-y-0.5"
                           style={{ animationDelay: `${Math.min(i * 40, 500)}ms`, borderTop: `3px solid ${colorFor(p.name)}` }}>
                    <div className="flex items-center gap-2.5">
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[12px] font-semibold text-white" style={{ background: colorFor(p.name) }}>
                        {p.name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
                      </span>
                      <div className="min-w-0">
                        <h3 className="truncate text-[15px] font-semibold">{p.name}</h3>
                        <p className="text-[12px] text-graphite">{p.caps.length} capabilit{p.caps.length === 1 ? "y" : "ies"}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {p.caps.map((c) => {
                        const hit = f && c.toLowerCase().includes(f);
                        return (
                          <span key={c} className={`rounded-full border px-2 py-0.5 text-[11.5px] ${hit ? "border-signal bg-[#F5F9FF] text-signal" : "border-rule text-ink"}`}>{c}</span>
                        );
                      })}
                    </div>
                  </article>
                ))}
                {!shownProjects.length && <p className="text-[13px] text-graphite">Nothing matches “{filter}”.</p>}
              </div>
            </>
          )
        ) : tab === "lessons" ? (
          lessons.length === 0 ? (
            <p className="text-[13px] text-graphite">Nothing yet: lessons are recorded when a run finishes.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                <span className="text-graphite">Learned in</span>
                {lessonProjects.map((p) => (
                  <button key={p} type="button" onClick={() => setProject(project === p ? null : p)}
                          className={`rounded-full border px-2.5 py-0.5 transition ${project === p ? "border-signal bg-[#F5F9FF] text-signal" : "border-rule text-graphite hover:text-ink"}`}>
                    {p} <span className="font-mono text-[10.5px]">{lessons.filter((l) => (l.project ?? l.run_id) === p).length}</span>
                  </button>
                ))}
                <span className="ml-auto text-graphite">The Developer is shown the ones that apply before it writes a similar story.</span>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {shownLessons.map((l, i) => (
                  <article key={l.id} className="enter flex gap-3 rounded-xl border border-rule bg-paper p-4 shadow-spectrum" style={{ animationDelay: `${Math.min(i * 35, 500)}ms` }}>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#E68619]/12 text-[#CB5D00]"><Icon name="flask" size={14} /></span>
                    <div className="min-w-0">
                      <p className="text-[13.5px] leading-snug">{l.lesson}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px]">
                        <span className="rounded-full bg-mist px-2 py-0.5 text-graphite">{l.story_id} · {l.applies_to}</span>
                        <Link href={`/runs/${l.run_id}`} className="rounded-full px-2 py-0.5 hover:underline"
                              style={{ color: colorFor(l.project ?? ""), background: `${colorFor(l.project ?? "")}14` }}>{l.project ?? l.run_id}</Link>
                      </div>
                    </div>
                  </article>
                ))}
                {!shownLessons.length && <p className="text-[13px] text-graphite">Nothing matches.</p>}
              </div>
            </>
          )
        ) : (
          <div className="rounded-xl border border-rule bg-paper p-4 shadow-spectrum">
            <ul className="grid gap-x-8 gap-y-2.5 md:grid-cols-2">
              {shownStack.map((t, i) => (
                <li key={t.technology} className="text-[13px]">
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium">{t.technology}</span>
                    {t.category && t.category !== "unknown" && <span className="text-[11px] text-graphite">{t.category}</span>}
                    <span className="ml-auto font-mono text-[11.5px] text-graphite">{t.projects} project{t.projects === 1 ? "" : "s"}</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-mist">
                    <div className="bar-grow h-full rounded-full" style={{ width: `${Math.max(4, (t.projects / maxStack) * 100)}%`, background: colorFor(t.technology), animationDelay: `${i * 30}ms` }} />
                  </div>
                </li>
              ))}
            </ul>
            {!shownStack.length && <p className="text-[13px] text-graphite">Nothing matches.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
