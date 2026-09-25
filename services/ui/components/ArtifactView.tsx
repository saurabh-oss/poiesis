"use client";

import { API, type Artifact } from "@/lib/api";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-rule py-3 first:border-t-0">
      <p className="text-[12px] font-medium text-graphite">{label}</p>
      <div className="mt-1 text-[14px] leading-relaxed">{children}</div>
    </div>
  );
}

function Bullets({ items }: { items: any[] }) {
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((x, i) => (
        <li key={i}>{typeof x === "string" ? x : JSON.stringify(x)}</li>
      ))}
    </ul>
  );
}

/** What the platform saw when it opened the running app in a real browser. */
function BrowserCheck({ runId, version, v }: { runId: string; version: string; v: any }) {
  const screens: any[] = (v.screens ?? []).filter((s: any) => !s.example);
  const problems: string[] = v.problems ?? [];
  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center gap-2">
        <h4 className="text-[13px] font-medium">Checked in a real browser</h4>
        <span className={`rounded border px-2 py-0.5 font-mono text-[11px] ${v.ok ? "border-moss text-moss" : "border-rust text-rust"}`}>
          {v.ok ? `${screens.length} screen${screens.length === 1 ? "" : "s"} working` : "problems found"}
        </span>
      </div>
      {problems.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-rust">
          {problems.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      )}
      {(v.backend_errors ?? []).length > 0 && (
        <div>
          <p className="text-[12px] font-medium text-graphite">The backend raised</p>
          <pre className="tape mt-1 max-h-[220px] overflow-auto whitespace-pre-wrap rounded bg-mist p-2 font-mono text-[11px] text-rust">
            {(v.backend_errors as string[]).join("\n\n")}
          </pre>
        </div>
      )}
      {screens.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {screens.map((s) => (
            <figure key={s.id} className="overflow-hidden rounded border border-rule bg-paper">
              {s.shot && runId && (
                <a href={`${API}/api/runs/${runId}/shots/${s.shot}?v=${version}`} target="_blank" rel="noreferrer">
                  <img
                    src={`${API}/api/runs/${runId}/shots/${s.shot}?v=${version}`}
                    alt={`Screenshot of the ${s.title} screen`}
                    className="block max-h-[220px] w-full border-b border-rule object-cover object-top"
                    loading="lazy"
                  />
                </a>
              )}
              <figcaption className="space-y-1 px-3 py-2 text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className={s.ok ? "text-moss" : "text-rust"}>{s.ok ? "works" : "broken"}</span>
                </div>
                {s.story && <p className="font-mono text-[11px] text-graphite">{s.story}</p>}
                {(s.problems ?? []).map((p: string, i: number) => (
                  <p key={i} className="text-rust">{p}</p>
                ))}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ArtifactView({ artifact }: { artifact: Artifact }) {
  const b = artifact.body ?? {};

  if (artifact.kind === "vision") {
    return (
      <div className="max-w-[68ch]">
        <h3 className="text-[22px] font-semibold tracking-[-0.01em]">{b.product_name}</h3>
        <p className="mt-2 text-[15px] leading-relaxed">{b.value_proposition}</p>
        <Field label="Problem">{b.problem_statement}</Field>
        <Field label="Who it is for">
          <Bullets items={(b.target_users ?? []).map((u: any) => `${u.persona} — ${u.current_pain}`)} />
        </Field>
        <Field label="How success is measured">
          <Bullets items={(b.success_metrics ?? []).map(
            (m: any) => `${m.metric}: ${m.baseline} → ${m.target} (${m.how_measured})`
          )} />
        </Field>
        <Field label="Deliberately not doing"><Bullets items={b.explicitly_out_of_scope ?? []} /></Field>
      </div>
    );
  }

  if (artifact.kind === "backlog") {
    const cov = b.coverage;
    const missing: string[] = cov?.missing ?? [];
    const excused = (cov?.rows ?? []).filter((r: any) => r.status === "excused");
    return (
      <div className="space-y-6">
        {cov && (
          <div className={`rounded border p-3 text-[13px] ${missing.length ? "border-rust/40 bg-rust/[0.04]" : "border-moss/40 bg-moss/[0.04]"}`}>
            <p className="font-semibold">
              Covers {cov.covered} of {cov.total} requirements of the brief
              {cov.excused ? `, ${cov.excused} left out with a reason` : ""}
            </p>
            {missing.length > 0 && (
              <p className="mt-1 text-rust">Still without a story: <span className="font-mono">{missing.join(", ")}</span></p>
            )}
            {excused.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-graphite">
                {excused.map((r: any) => <li key={r.id}><span className="font-mono">{r.id}</span> {r.title}: {r.reason}</li>)}
              </ul>
            )}
          </div>
        )}
        {(b.epics ?? []).map((epic: any) => (
          <div key={epic.id}>
            <h3 className="text-[15px] font-semibold">{epic.title}</h3>
            <p className="text-[13px] text-graphite">{epic.outcome}</p>
            <div className="mt-3 space-y-3">
              {(b.stories ?? []).filter((s: any) => s.epic_id === epic.id).map((s: any) => (
                <article key={s.id} className="border-l-2 border-rule pl-4">
                  <p className="font-mono text-[12px] text-graphite">
                    {s.id} · value {s.value} · estimate {s.estimate}
                    {(s.covers ?? []).length > 0 && <> · delivers {(s.covers ?? []).join(", ")}</>}
                  </p>
                  <p className="text-[14px] font-medium">{s.title}</p>
                  <p className="text-[13px] text-graphite">{s.narrative}</p>
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[13px]">
                    {(s.acceptance_criteria ?? []).map((c: string, i: number) => <li key={i}>{c}</li>)}
                  </ul>
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (artifact.kind === "architecture") {
    return (
      <div className="space-y-4">
        <p className="max-w-[68ch] text-[15px] leading-relaxed">{b.context}</p>
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-rule text-left text-graphite">
              <th className="py-2 font-medium">Capability needed</th>
              <th className="py-2 font-medium">Verdict</th>
              <th className="py-2 font-medium">From the portfolio</th>
            </tr>
          </thead>
          <tbody>
            {(b.reuse_plan ?? []).map((r: any, i: number) => (
              <tr key={i} className="border-b border-rule/60 align-top">
                <td className="py-2 pr-4">{r.need}</td>
                <td className="py-2 pr-4">
                  <span className={r.verdict === "build_new" ? "text-ochre" : "text-moss"}>
                    {r.verdict === "build_new" ? "build new" : r.verdict}
                  </span>
                </td>
                <td className="py-2 font-mono text-[12px] text-graphite">
                  {r.component_id ?? r.rationale ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(b.decisions ?? []).map((d: any, i: number) => (
          <Field key={i} label={`Decision: ${d.title}`}>
            {d.decision}
            <p className="mt-1 text-[13px] text-graphite">{d.rationale}</p>
          </Field>
        ))}
      </div>
    );
  }

  if (artifact.kind === "review") {
    const dims = b.dimensions ?? {};
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-4 rounded border border-rule bg-mist/50 p-4">
          <p className="font-mono text-[34px] font-semibold leading-none tabular-nums">
            {b.weighted_score}<span className="text-[15px] text-graphite">/100</span>
          </p>
          <div className="text-[13px] text-graphite">
            <p>Ships at {b.threshold}</p>
            {(b.failing_stories ?? []).length > 0 && (
              <p className="text-rust">{b.failing_stories.length} red {b.failing_stories.length === 1 ? "story" : "stories"}</p>
            )}
          </div>
          <span className={`ml-auto rounded-full px-3 py-1 text-[13px] font-semibold ${b.computed_verdict === "rework" ? "bg-rust/10 text-rust" : "bg-moss/10 text-moss"}`}>
            {b.computed_verdict === "rework" ? "Rework" : b.computed_verdict === "ship_with_followups" ? "Ship, with follow-ups" : "Ship"}
          </span>
        </div>
        {b.verdict_rationale && <p className="text-[14px] leading-relaxed">{b.verdict_rationale}</p>}
        <div className="space-y-2">
          {Object.entries(dims).map(([k, v]: any) => (
            <div key={k}>
              <div className="flex items-baseline justify-between text-[13px]">
                <span>{k.replace(/_/g, " ")}</span>
                <span className="font-mono">{v.score}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-mist">
                <div
                  className={`bar-grow h-full rounded-full ${Number(v.score) >= (b.threshold ?? 70) ? "bg-moss" : Number(v.score) >= 50 ? "bg-ochre" : "bg-rust"}`}
                  style={{ width: `${v.score}%` }}
                />
              </div>
              <p className="mt-1 text-[12px] text-graphite">{v.notes}</p>
            </div>
          ))}
        </div>
        {(b.blocking_findings ?? []).length > 0 && (
          <Field label="Blocking findings">
            <Bullets items={(b.blocking_findings ?? []).map((f: any) => `${f.file}: ${f.finding}`)} />
          </Field>
        )}
      </div>
    );
  }

  if (artifact.kind === "discovery") {
    const questions = b.questions ?? [];
    const cost: Record<string, string> = {
      high: "bg-rust/10 text-rust", medium: "bg-ochre/10 text-ochre", low: "bg-moss/10 text-moss",
    };
    return (
      <div className="space-y-5">
        {b.understanding && (
          <blockquote className="border-l-4 border-signal/60 bg-signal/[0.04] px-4 py-3 text-[15px] leading-relaxed">
            {b.understanding}
          </blockquote>
        )}
        {(b.contradictions ?? []).length > 0 && (
          <Field label="Contradictions between your sources">
            <Bullets items={(b.contradictions ?? []).map((c: any) => c.description ?? c)} />
          </Field>
        )}
        {questions.length > 0 && (
          <div>
            <p className="text-[12px] font-medium text-graphite">Questions for you, most expensive to guess first</p>
            <div className="mt-2 space-y-2.5">
              {questions.map((q: any, i: number) => (
                <div key={q.id ?? i} className="rounded border border-rule p-3">
                  <div className="flex items-start gap-2">
                    <span className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase ${cost[q.cost_of_being_wrong] ?? "bg-mist text-graphite"}`}>
                      {q.cost_of_being_wrong ?? "open"}
                    </span>
                    <p className="text-[14px] font-medium">{q.question}</p>
                  </div>
                  {q.why_it_matters && <p className="mt-1.5 text-[12.5px] text-graphite">{q.why_it_matters}</p>}
                  {q.proposed_default && (
                    <p className="mt-2 text-[12.5px]"><span className="text-graphite">If you don't answer: </span>{q.proposed_default}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {(b.signals ?? []).length > 0 && (
          <Field label="What the evidence says">
            <Bullets items={(b.signals ?? []).map((s: any) => s.statement ?? s)} />
          </Field>
        )}
      </div>
    );
  }

  if (artifact.kind === "sprint") {
    return (
      <div className="space-y-5">
        <div className="rounded border border-signal/30 bg-signal/[0.04] p-4">
          <p className="text-[11.5px] font-semibold uppercase tracking-[0.07em] text-signal">Sprint goal</p>
          <p className="mt-1 text-[16px] font-medium leading-snug">{b.sprint_goal}</p>
        </div>
        <ol className="space-y-2.5">
          {(b.stories ?? []).map((s: any, i: number) => (
            <li key={s.id ?? i} className="flex items-start gap-3">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink font-mono text-[12px] font-semibold text-paper">
                {s.rank ?? i + 1}
              </span>
              <div>
                <p className="font-mono text-[12px] text-graphite">{s.id}</p>
                <p className="text-[13.5px]">{s.why_now}</p>
              </div>
            </li>
          ))}
        </ol>
        {(b.deferred ?? []).length > 0 && (
          <Field label="Deferred to a later sprint">
            <Bullets items={(b.deferred ?? []).map((d: any) => `${d.id}: ${d.why_not_now ?? ""}`)} />
          </Field>
        )}
        {(b.definition_of_done ?? []).length > 0 && (
          <Field label="Done means"><Bullets items={b.definition_of_done} /></Field>
        )}
      </div>
    );
  }

  if (artifact.kind === "test_report") {
    const stories = b.stories ?? [];
    return (
      <div className="space-y-4">
        <p className="text-[15px]">
          <span className="font-semibold text-moss">{b.green ?? 0}</span> of {b.total ?? stories.length} stories green.
        </p>
        {stories.map((s: any, i: number) => (
          <div key={s.story_id ?? i} className="rounded border border-rule p-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${s.status === "green" ? "bg-moss/10 text-moss" : "bg-rust/10 text-rust"}`}>
                {s.status}
              </span>
              <span className="font-mono text-[12px] text-graphite">{s.story_id}</span>
              <span className="text-[14px] font-medium">{s.title}</span>
              <span className="ml-auto font-mono text-[11.5px] text-graphite">
                {s.repair_attempts ?? 0} repairs{s.tests_revised ? " · tests revised" : ""}
              </span>
            </div>
            {(s.criteria_covered ?? []).length > 0 && (
              <ul className="mt-2 space-y-1 text-[13px]">
                {s.criteria_covered.map((c: any, j: number) => (
                  <li key={j} className="flex gap-2">
                    <span className="text-moss">✓</span>
                    <span>
                      {typeof c === "string" ? c : c.criterion}
                      {typeof c !== "string" && c.test && <span className="ml-1.5 font-mono text-[11.5px] text-graphite">{c.test}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {(s.criteria_not_covered ?? []).length > 0 && (
              <ul className="mt-1 space-y-1 text-[13px]">
                {s.criteria_not_covered.map((c: any, j: number) => (
                  <li key={j} className="flex gap-2">
                    <span className="text-ochre">○</span>
                    <span>{typeof c === "string" ? c : `${c.criterion}${c.why ? ` — ${c.why}` : ""}`}</span>
                  </li>
                ))}
              </ul>
            )}
            {s.test_output && (
              <details className="mt-2">
                <summary className="cursor-pointer text-[12px] text-graphite">Test output</summary>
                <pre className="tape mt-1.5 max-h-[240px] overflow-auto whitespace-pre-wrap rounded bg-mist p-2.5 font-mono text-[11px]">{s.test_output}</pre>
              </details>
            )}
          </div>
        ))}
      </div>
    );
  }

  if (artifact.kind === "scaffold") {
    return (
      <div className="space-y-4">
        <p className="text-[15px]">
          <span className="rounded bg-ink px-2 py-0.5 font-mono text-[12px] text-paper">{b.archetype}</span>
          <span className="ml-2">{b.description}</span>
        </p>
        <div className="flex flex-wrap gap-2">
          {(b.services ?? []).map((s: any) => (
            <span key={s.name} className="inline-flex items-center gap-1.5 rounded border border-rule bg-mist px-2.5 py-1 text-[13px]">
              <span className="font-medium">{s.name}</span>
              {s.port && <span className="font-mono text-[11.5px] text-graphite">:{s.port}</span>}
              <span className="text-[11.5px] text-graphite">{s.role}</span>
            </span>
          ))}
        </div>
        {(b.definition_of_deployable ?? []).length > 0 && (
          <Field label="Counts as deployable when"><Bullets items={b.definition_of_deployable} /></Field>
        )}
        <p className="font-mono text-[12px] text-graphite">
          {(b.files ?? []).length} files written · {(b.protected ?? []).length} protected from edits
        </p>
      </div>
    );
  }

  if (artifact.kind === "release") {
    if (b.status === "held") {
      return <p className="text-[15px]">Release held.{b.notes ? ` ${b.notes}` : ""}</p>;
    }
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full bg-moss/10 px-3 py-1 font-mono text-[14px] font-semibold text-moss">v{b.version}</span>
          {b.url && (
            <a href={b.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded bg-signal px-3 py-1.5 text-[13px] font-medium text-paper hover:bg-[#0054B6]">
              Open {b.url} ↗
            </a>
          )}
        </div>
        {b.release_notes_markdown && (
          <div className="whitespace-pre-wrap rounded border border-rule bg-paper p-4 text-[14px] leading-relaxed">
            {b.release_notes_markdown}
          </div>
        )}
        {(b.smoke_checks ?? []).length > 0 && (
          <Field label="Try these"><Bullets items={(b.smoke_checks ?? []).map((c: any) => c.description ?? c)} /></Field>
        )}
        {(b.known_limitations ?? []).length > 0 && (
          <Field label="Known limitations"><Bullets items={b.known_limitations} /></Field>
        )}
      </div>
    );
  }

  if (artifact.kind === "deployment") {
    return (
      <div className="space-y-3">
        {b.status === "running" ? (
          <p className="text-[15px]">
            Running at{" "}
            <a href={b.url} target="_blank" rel="noreferrer" className="font-medium text-signal underline">
              {b.url}
            </a>
          </p>
        ) : (
          <p className="text-[15px]">
            Status: <span className="font-medium">{b.status}</span>
          </p>
        )}
        {b.detail && (
          <pre className="tape overflow-x-auto whitespace-pre-wrap rounded bg-mist p-3 font-mono text-[12px] text-graphite">
            {b.detail}
          </pre>
        )}
        {b.verification && !b.verification.skipped && (
          <BrowserCheck runId={b.run_id} version={artifact.id} v={b.verification} />
        )}
      </div>
    );
  }

  return (
    <pre className="tape overflow-x-auto bg-mist p-4 font-mono text-[12px] leading-relaxed">
      {JSON.stringify(b, null, 2)}
    </pre>
  );
}
