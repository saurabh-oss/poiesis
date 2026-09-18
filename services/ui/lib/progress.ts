/**
 * Everything the run page says about progress is derived here from two things
 * the orchestrator already records: the event stream and the artifacts. Keeping
 * it in one pure module means the rail, the header, the stage panel and the
 * build board can never disagree about where a run is.
 */
import type { Artifact, PoiesisEvent, RunDetail, Stage } from "./api";
import { QUIET_AGENTS } from "./agents";

export type StageState = "done" | "active" | "gate" | "failed" | "held" | "next" | "ahead";

export type StageSpan = {
  start: number | null;
  end: number | null;
  count: number;
  last: PoiesisEvent | null;
  lastWorker: PoiesisEvent | null;
  warnings: number;
  errors: number;
  agents: string[];
};

export function eventTime(e: PoiesisEvent): number {
  return e.at ? Date.parse(e.at) : NaN;
}

export function timeline(stages: Stage[], events: PoiesisEvent[]): Record<string, StageSpan> {
  const spans: Record<string, StageSpan> = {};
  for (const s of stages) {
    spans[s.key] = {
      start: null, end: null, count: 0, last: null, lastWorker: null,
      warnings: 0, errors: 0, agents: [],
    };
  }
  for (const e of events) {
    const span = spans[e.stage];
    if (!span) continue;
    const t = eventTime(e);
    if (!Number.isNaN(t)) {
      if (span.start === null || t < span.start) span.start = t;
      if (span.end === null || t > span.end) span.end = t;
    }
    span.count += 1;
    span.last = e;
    if (e.level === "warn") span.warnings += 1;
    if (e.level === "error") span.errors += 1;
    if (!QUIET_AGENTS.has(e.agent)) {
      span.lastWorker = e;
      if (!span.agents.includes(e.agent)) span.agents.push(e.agent);
    }
  }
  return spans;
}

/**
 * Where every stage stands.
 *
 * The run row's `stage` becomes "done" once harvest finishes, which is not a
 * stage key. The old rail fell back to index 0 for it, so a finished run showed
 * Intake as the stage in progress.
 */
export function stageStates(
  stages: Stage[], run: RunDetail, gateStage: string | undefined,
  spans: Record<string, StageSpan>,
): Record<string, StageState> {
  const out: Record<string, StageState> = {};
  const keys = stages.map((s) => s.key);
  if (!keys.length) return out;

  if (run.status === "complete" || run.stage === "done") {
    keys.forEach((k) => { out[k] = "done"; });
    return out;
  }
  if (run.status === "queued") {
    keys.forEach((k, i) => { out[k] = i === 0 ? "next" : "ahead"; });
    return out;
  }

  let current = keys.indexOf(run.stage);
  if (current < 0 || run.status === "failed") {
    let furthest = 0;
    keys.forEach((k, i) => { if (spans[k]?.count) furthest = i; });
    current = Math.max(current, furthest);
  }

  keys.forEach((k, i) => {
    if (i < current) out[k] = "done";
    else if (i > current) out[k] = i === current + 1 ? "next" : "ahead";
    else if (run.status === "failed") out[k] = "failed";
    else if (run.status === "held") out[k] = "held";
    else if (gateStage === k || run.status === "waiting") out[k] = "gate";
    else out[k] = "active";
  });
  return out;
}

/** The stage the run is actually on, even when the row says "done" or "failed". */
export function liveStage(stages: Stage[], run: RunDetail, spans: Record<string, StageSpan>): string {
  if (stages.some((s) => s.key === run.stage)) return run.stage;
  let last = stages[0]?.key ?? "intake";
  for (const s of stages) if (spans[s.key]?.count) last = s.key;
  return last;
}

/** Time in stage: until the next stage began, or until now while it is still open. */
export function stageDuration(
  key: string, stages: Stage[], spans: Record<string, StageSpan>, now: number, state?: StageState,
): number | null {
  const span = spans[key];
  if (!span || span.start === null) return null;
  if (state === "active" || state === "gate") return Math.max(0, now - span.start);
  const index = stages.findIndex((s) => s.key === key);
  let next: number | null = null;
  for (const s of stages.slice(index + 1)) {
    const st = spans[s.key]?.start;
    if (st !== null && st !== undefined && st >= span.start) next = next === null ? st : Math.min(next, st);
  }
  return Math.max(0, (next ?? span.end ?? span.start) - span.start);
}

export function percent(stages: Stage[], states: Record<string, StageState>, stories: StoryCard[]): number {
  if (!stages.length) return 0;
  let score = 0;
  for (const s of stages) {
    const st = states[s.key];
    if (st === "done") score += 1;
    else if (st === "active" || st === "gate" || st === "held") {
      if (s.key === "build" && stories.length) {
        score += stories.filter((c) => SETTLED.has(c.state)).length / stories.length;
      } else {
        score += 0.5;
      }
    }
  }
  return Math.min(100, Math.round((score / stages.length) * 100));
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const diff = Math.max(0, now - Date.parse(iso));
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  // 24-hour on purpose: a locale's "AM"/"PM" suffix overflows the time column
  // in the activity feed and the stage log.
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

/** One artifact per kind: the latest version, which is the one the run acted on. */
export function latestByKind(artifacts: Artifact[]): Artifact[] {
  const byKind = new Map<string, Artifact>();
  for (const a of artifacts) {
    const prior = byKind.get(a.kind);
    if (!prior || a.version >= prior.version) byKind.set(a.kind, a);
  }
  return [...byKind.values()];
}

// --- the build board -----------------------------------------------------------

export type StoryState =
  | "queued" | "implementing" | "testing" | "repairing" | "revising"
  | "green" | "red" | "blocked" | "dropped";

export type StoryCard = {
  id: string;
  title: string;
  state: StoryState;
  attempts: number;
  files: number;
  covered: string;
  note: string;
  revised: boolean;
  why: string;
};

const SETTLED = new Set<StoryState>(["green", "red", "blocked", "dropped"]);
const STORY_ID = /\b(S\d+)\b/;

function latestBody(artifacts: Artifact[], kind: string): any {
  let best: Artifact | undefined;
  for (const a of artifacts) if (a.kind === kind && (!best || a.version >= best.version)) best = a;
  return best?.body;
}

/**
 * Story-by-story state for the build stage, read from the Developer's and
 * Tester's narration. When `settled`, the test report overrides it: that is the
 * build's final word, whereas live narration may be mid-replay after a gate.
 */
export function storyBoard(events: PoiesisEvent[], artifacts: Artifact[], settled: boolean): StoryCard[] {
  const sprint = latestBody(artifacts, "sprint");
  const backlog = latestBody(artifacts, "backlog");
  const titles: Record<string, string> = {};
  for (const s of backlog?.stories ?? []) if (s?.id) titles[s.id] = s.title ?? s.id;

  const cards = new Map<string, StoryCard>();
  const blank = (id: string, why = ""): StoryCard => ({
    id, title: titles[id] ?? id, state: "queued", attempts: 0, files: 0,
    covered: "", note: "Waiting its turn", revised: false, why,
  });
  for (const s of sprint?.stories ?? []) if (s?.id) cards.set(s.id, blank(s.id, s.why_now ?? ""));

  let current: string | null = null;
  for (const e of events) {
    if (e.stage !== "build") continue;
    const msg = e.message;
    const named: string | null = msg.match(STORY_ID)?.[1] ?? null;
    const id: string | null = named ?? current;
    if (!id) continue;
    const card = cards.get(id) ?? blank(id);
    cards.set(id, card);

    if (/^Starting S\d+/.test(msg)) {
      current = id;
      card.state = "implementing";
      card.attempts = 0;
      card.revised = false;
      const title = msg.split(":").slice(1).join(":").trim();
      if (title) card.title = title;
      card.note = "Writing the implementation";
    } else if (/implemented in (\d+) files/.test(msg)) {
      card.files = Number(msg.match(/implemented in (\d+) files/)?.[1] ?? 0);
      card.state = "testing";
      card.note = "The Tester is writing tests against the acceptance criteria";
    } else if (!named && /criteria under test/.test(msg)) {
      card.covered = msg.split(" ")[0];
      card.state = "testing";
      card.note = "Running the tests in a sandbox";
    } else if (/Tester revised/.test(msg)) {
      card.revised = true;
      card.state = "revising";
      card.note = "The Tester corrected its own tests against the verified contract";
    } else if (/one repair against the revised tests/.test(msg)) {
      card.attempts += 1;
      card.state = "repairing";
      card.note = "One more repair, against the corrected tests";
    } else if (/repair attempt (\d+)/.test(msg)) {
      card.attempts = Number(msg.match(/repair attempt (\d+)/)?.[1] ?? card.attempts);
      card.state = "repairing";
      card.note = `Tests failing, so the Developer is repairing (attempt ${card.attempts})`;
    } else if (/ is green after/.test(msg)) {
      card.state = "green";
      card.note = "Every test passes";
    } else if (/ is red after/.test(msg)) {
      card.state = "red";
      card.note = "Still failing after its repairs";
    } else if (/ blocked:/.test(msg)) {
      card.state = "blocked";
      card.note = msg.split("blocked:")[1]?.trim() ?? "Blocked";
    } else if (/could not be parsed/.test(msg)) {
      card.state = "red";
      card.note = "A model reply could not be read";
    } else if (/: dropped from the sprint/.test(msg)) {
      card.state = "dropped";
      card.note = msg.split(":").slice(2).join(":").trim() || "Dropped from the sprint";
    }
  }

  if (settled) {
    const report = latestBody(artifacts, "test_report");
    for (const s of report?.stories ?? []) {
      const card = cards.get(s.story_id);
      if (card && SETTLED.has(s.status)) {
        card.state = s.status;
        card.attempts = s.repair_attempts ?? card.attempts;
        if (s.status === "green") card.note = "Every test passes";
        if (s.status === "red") card.note = "Still failing after its repairs";
        if (s.status === "dropped") card.note = s.reason || "Dropped from the sprint";
      }
    }
  }
  return [...cards.values()];
}
