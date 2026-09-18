"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, type RunSummary, type Stage } from "@/lib/api";
import { useNow } from "@/lib/useNow";
import Icon from "@/components/Icon";
import BriefCoach from "@/components/home/BriefCoach";
import Cast from "@/components/home/Cast";
import FileDrop from "@/components/home/FileDrop";
import LinkChips from "@/components/home/LinkChips";
import RecentRuns from "@/components/home/RecentRuns";
import StreamBand from "@/components/home/StreamBand";

const EXAMPLES = [
  {
    title: "Team leave tracker",
    brief: "Our team has no simple way to see who is on leave. People book time off over email and managers lose track, so we end up with three people away in the same week. I want a small internal web page where anyone can record a leave request with a start and end date, and everyone can see who is off and when. No approval workflow for now.",
  },
  {
    title: "Application drop-off",
    brief: "We keep losing candidates part-way through the job application form. Recruiters say people call the helpdesk asking to carry on where they left off, and we tell them to start again. Legal will not let us store a half-finished application for more than 30 days. I want this fixed before the graduate intake in March.",
  },
  {
    title: "Visitor sign-in",
    brief: "Reception signs visitors in on a paper sheet, so nobody knows who is in the building during a fire drill. I want a simple sign-in page on the reception tablet that records the visitor's name, who they are visiting and the time, and a live list of everyone currently on site. Visitor details must be deleted after 30 days.",
  },
];

type Step = { label: string; state: "pending" | "active" | "done" };

function Field({
  n, label, hint, htmlFor, children,
}: { n: number; label: string; hint?: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2.5">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ink text-[11px] font-semibold text-paper">{n}</span>
        <label htmlFor={htmlFor} className="text-[14px] font-semibold">{label}</label>
      </div>
      {hint && <p className="ml-[30px] mt-0.5 text-[12.5px] text-graphite">{hint}</p>}
      <div className="ml-[30px] mt-2">{children}</div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const now = useNow(30000);
  const [stages, setStages] = useState<Stage[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [health, setHealth] = useState<{ llm_profile: string; pack: string } | null>(null);
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [links, setLinks] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(0);

  useEffect(() => {
    api.stages().then(setStages).catch(() => undefined);
    api.health().then(setHealth).catch(() => setHealth(null));
    api.listRuns()
      .then(setRuns)
      .catch(() => setError("The orchestrator is not answering on port 8080. Start it with docker compose up -d, then reload."))
      .finally(() => setLoaded(true));
  }, []);

  const canStart = !steps && (brief.trim().length > 0 || links.length > 0 || files.length > 0);

  async function start() {
    setError(null);
    let list: Step[] = [
      { label: "Creating the run", state: "active" },
      ...(files.length
        ? [{ label: `Reading ${files.length} file${files.length === 1 ? "" : "s"}`, state: "pending" as const }]
        : []),
      { label: "Waking the agents", state: "pending" },
    ];
    const mark = (i: number, state: Step["state"]) => {
      list = list.map((s, j) => (j === i ? { ...s, state } : s));
      setSteps(list);
    };
    setSteps(list);
    try {
      const sources = [
        ...(brief.trim() ? [{ kind: "text", value: brief, label: "stakeholder brief" }] : []),
        ...links.map((l) => ({ kind: "url", value: l, label: l })),
      ];
      // Create, finish intake, then start: intake reads the evidence once, so
      // uploads have to land before the agents wake.
      const { id } = await api.createRun({ title: title.trim() || "Untitled brief", sources });
      mark(0, "done");
      let i = 1;
      if (files.length) {
        mark(i, "active");
        await api.upload(id, files);
        mark(i, "done");
        i += 1;
      }
      mark(i, "active");
      await api.startRun(id);
      mark(i, "done");
      router.push(`/runs/${id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "The run could not be started.");
      setSteps(null);
    }
  }

  return (
    <div className="space-y-10">
      <section className="space-y-6">
        <div className="enter max-w-[780px]">
          {health && (
            <p className="inline-flex items-center gap-2 rounded-full border border-moss/30 bg-moss/[0.06] px-3 py-1 text-[12px] font-medium text-moss">
              <span className="live-dot live-dot-moss" />
              Ready · {health.llm_profile === "local" ? "models running on your own GPU" : `${health.llm_profile} models`} · {health.pack} pack
            </p>
          )}
          <h1 className="mt-4 text-[42px] font-semibold leading-[1.06] tracking-[-0.03em]">
            Describe the problem.
            <br />
            <span className="text-signal">Watch it get built.</span>
          </h1>
          <p className="mt-4 max-w-[64ch] text-[16px] leading-relaxed text-graphite">
            Hand over whatever you already have. Eight agents read it, question it, plan it, build it,
            test it and start it running, and they stop to ask you whenever a decision would change
            the outcome.
          </p>
        </div>
        <div className="enter rounded border border-rule bg-paper px-5 pb-4 pt-5 shadow-spectrum" style={{ animationDelay: "80ms" }}>
          <StreamBand stages={stages} />
          <p className="mt-3 text-center text-[12px] text-graphite">
            {stages.length ? `${stages.length} stages` : "Every stage"} from your words to a running app. The ones marked
            “you decide” stop for your answer.
          </p>
        </div>
      </section>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="enter rounded border border-rule bg-paper p-6 shadow-spectrum sm:p-7" style={{ animationDelay: "140ms" }}>
          <div className="space-y-7">
            <Field n={1} label="Name it" htmlFor="title" hint="A working title. The Product Owner will propose a product name.">
              <input
                id="title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Team leave tracker"
                className="w-full border border-rule px-3 py-2 text-[14px]"
              />
            </Field>

            <Field n={2} label="Say it in your own words" htmlFor="brief" hint="What is going wrong, for whom, and what must stay true. Plain language is best.">
              <textarea
                key={flash}
                id="brief"
                rows={7}
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                placeholder={EXAMPLES[1].brief}
                className={`w-full resize-y border border-rule px-3 py-2.5 text-[14px] leading-relaxed ${flash ? "enter" : ""}`}
              />
              <BriefCoach text={brief} />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-[12px] text-graphite">Or start from an example:</span>
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.title}
                    type="button"
                    onClick={() => { setTitle(ex.title); setBrief(ex.brief); setFlash((f) => f + 1); }}
                    className="inline-flex items-center gap-1 rounded-full border border-rule bg-paper px-2.5 py-1 text-[12px] transition-colors hover:border-signal/50 hover:text-signal"
                  >
                    <Icon name="spark" size={11} /> {ex.title}
                  </button>
                ))}
              </div>
            </Field>

            <div className="grid gap-7 md:grid-cols-2">
              <Field n={3} label="Add what you already have">
                <FileDrop files={files} onChange={setFiles} />
              </Field>
              <Field n={4} label="Add links">
                <LinkChips links={links} onChange={setLinks} />
              </Field>
            </div>

            {error && (
              <p className="flex items-start gap-2 rounded border border-rust/30 bg-rust/[0.05] px-3 py-2 text-[13px] text-rust">
                <Icon name="alert" size={15} className="mt-0.5 shrink-0" /> {error}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-4 border-t border-rule pt-5">
              <button
                onClick={start}
                disabled={!canStart}
                className="group inline-flex items-center gap-2 rounded bg-signal px-6 py-2.5 text-[15px] font-semibold text-paper shadow-spectrum transition-colors hover:bg-[#0054B6] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Start the run
                <Icon name="arrow" size={16} className="transition-transform group-hover:translate-x-0.5" />
              </button>
              {steps ? (
                <ol className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  {steps.map((s) => (
                    <li
                      key={s.label}
                      className={`inline-flex items-center gap-1.5 text-[13px] ${
                        s.state === "done" ? "text-moss" : s.state === "active" ? "text-signal" : "text-graphite"
                      }`}
                    >
                      {s.state === "done" ? (
                        <Icon name="check" size={14} strokeWidth={2.6} className="pop" />
                      ) : s.state === "active" ? (
                        <span className="spin inline-block h-3.5 w-3.5 rounded-full border-2 border-signal/25 border-t-signal" />
                      ) : (
                        <span className="h-1.5 w-1.5 rounded-full bg-rule" />
                      )}
                      {s.label}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-[12.5px] text-graphite">
                  {canStart
                    ? "The Analyst reads it first, and asks about anything it can't work out."
                    : "Add a brief, a link or a file to begin."}
                </p>
              )}
            </div>
          </div>
        </section>

        <aside className="space-y-6">
          <Cast stages={stages} />
          <RecentRuns runs={runs} stages={stages} loaded={loaded} now={now} />
        </aside>
      </div>
    </div>
  );
}
