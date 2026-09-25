/* Poiesis project site: the replay, the value stream, the architecture and the rest.
   Everything is plain JavaScript over the data below; the content comes from the
   repository's documentation and the DupeGuard run's event log. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") {
        for (const [p, x] of Object.entries(v)) p.startsWith("--") ? el.style.setProperty(p, x) : (el.style[p] = x);
      }
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
    return el;
  };
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- data */
  const AGENTS = {
    analyst: { name: "Analyst", color: "#5258E4", initials: "An" },
    product_owner: { name: "Product Owner", color: "#8A3FD6", initials: "PO" },
    architect: { name: "Architect", color: "#B130BD", initials: "Ar" },
    planner: { name: "Planner", color: "#0D8A80", initials: "Pl" },
    foundation: { name: "Foundation Dev", color: "#4F7F12", initials: "Fd" },
    data_designer: { name: "Data Designer", color: "#0B78B8", initials: "Dd" },
    developer: { name: "Developer", color: "#0265DC", initials: "De" },
    tester: { name: "Tester", color: "#C8336E", initials: "Te" },
    reviewer: { name: "Reviewer", color: "#1D6F8C", initials: "Re" },
    release: { name: "Release Mgr", color: "#007A4D", initials: "RM" },
    governance: { name: "Governance", color: "#9A6B12", initials: "Go" },
    platform: { name: "Platform", color: "#6E6E6E", initials: "Po" },
  };

  const STAGES = [
    { key: "intake", label: "Intake", icon: "M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v6H3v-6z", agents: [],
      reads: "Documents (PDF, DOCX with its tables in order), images, audio, URLs, text", produces: "Cited evidence fragments that everything downstream must cite by id",
      example: "20 fragments: the Director's brief, and 19 from BRD-SUP-2026-021" },
    { key: "discovery", label: "Discovery", gate: "clarify", icon: "M11 4.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM20.5 20.5 16 16", agents: ["analyst"],
      reads: "The evidence", produces: "Understanding, contradictions, and at most six questions ranked by the cost of being wrong — each with a default",
      example: "6 open questions; 2 contradictions found" },
    { key: "vision", label: "Vision", gate: "approve_vision", icon: "M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12zM12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6z", agents: ["product_owner"],
      reads: "Evidence and clarifications", produces: "Problem, value, users, success metrics, scope and risks — every claim cited, no technology named",
      example: "Refuses to assert anything it cannot cite" },
    { key: "backlog", label: "Backlog", gate: "approve_backlog", icon: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01", agents: ["product_owner"],
      reads: "The vision", produces: "Epics and stories, each with at least two Given/When/Then criteria and a cited source",
      example: "1 epic, 10 stories, 54 points" },
    { key: "architecture", label: "Architecture", gate: "approve_architecture", icon: "m12 3 9 5-9 5-9-5 9-5zM3 13l9 5 9-5", agents: ["architect"],
      reads: "Vision, backlog, and the portfolio knowledge graph — by word and by meaning", produces: "A reuse verdict per capability (reuse, extend, build new with a written rationale), decisions, a diagram",
      example: "Recorded 1 reuse edges in the knowledge graph" },
    { key: "sprint", label: "Sprint", gate: "approve_sprint", icon: "M5 21V4M5 4h11l-2.2 4L16 12H5", agents: ["planner"],
      reads: "Backlog and reuse plan", produces: "A sprint goal and ranked stories within capacity and dependencies",
      example: "Sprint 1 goal: Establish the foundational data models and core duplicate detection engine…" },
    { key: "scaffold", label: "Scaffold", icon: "M3.5 3.5h17v17h-17zM3.5 9.5h17M9.5 9.5v11", agents: [],
      reads: "The archetype", produces: "A working app before any feature code: gateway, api, data service and Postgres; the UI kit, shell and design system. No model call",
      example: "Every generated app has the same topology" },
    { key: "foundation", label: "Foundation", icon: "M4 20h16M6 20V9l6-5 6 5v11M10 20v-6h4v6", agents: ["foundation", "data_designer"],
      reads: "The brief and every story's criteria", produces: "The whole data model at once, then demonstration data from a checked spec, loaded into init.sql",
      example: "Data model in place: 11 table(s) — agent, audit_entry, cluster, customer…" },
    { key: "build", label: "Build", gate: "failed_story", icon: "m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16", agents: ["developer", "tester"],
      reads: "One story, the architecture, the routes and tables that exist, the lessons that apply", produces: "Files and a commit per story — checked, repaired up to three times, then smoked against Postgres",
      example: "S2 is green after 0 repair attempt(s)" },
    { key: "deploy", label: "Deploy", icon: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18", agents: ["release"],
      reads: "The increment", produces: "The app on its own port, then every screen opened and used in a headless browser and screenshotted; a codebase map",
      example: "Checked in a browser: 10 screen(s), all working" },
    { key: "review", label: "Review", icon: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm-3.5 9.2 2.3 2.3 4.7-4.8", agents: ["reviewer"],
      reads: "Diff, criteria, reuse plan, and what every screen displayed", produces: "Five weighted scores, findings, blockers — a computed verdict; rework returns to build with the findings",
      example: "weighted score 90.8/100 (threshold 60), 0 blockers" },
    { key: "release", label: "Release", gate: "approve_release", icon: "m3 7.5 9-4.5 9 4.5v9L12 21l-9-4.5zM3 7.5l9 4.5 9-4.5M12 12v9", agents: ["release"],
      reads: "Everything", produces: "Release, release a smaller base app dropping what is broken, send back for another round, or hold — the only gate that is never automatic",
      example: "It arrives with the app already running and a link to it" },
    { key: "harvest", label: "Harvest", icon: "M6 4.2a2.3 2.3 0 1 1 0 4.6 2.3 2.3 0 0 1 0-4.6zM18 5.7a2.3 2.3 0 1 1 0 4.6 2.3 2.3 0 0 1 0-4.6zM9.5 15.7a2.3 2.3 0 1 1 0 4.6 2.3 2.3 0 0 1 0-4.6zM8.2 7.1l7.5 1.1M7.1 8.6l1.6 7.3M16.4 9.8l-5 6.6", agents: [],
      reads: "The finished run", produces: "Stories, decisions, capabilities and one lesson per failed or repaired story — into the graph and the vector index, for the next run",
      example: "The next Developer is shown the lessons that apply" },
  ];

  const AGENT_CARDS = [
    ["analyst", "reasoning", "Argues with the brief: contradictions, and the questions whose wrong answer costs most.", "Ask more than six questions, or ask what the evidence already answers"],
    ["product_owner", "reasoning", "Writes the vision and the backlog; every claim cites a fragment of evidence.", "Assert anything it cannot cite; name a technology in the vision"],
    ["architect", "reasoning", "Designs against what the portfolio already has; a reuse verdict for every capability.", "Build new without a written rationale"],
    ["planner", "fast", "Cuts the slice that gets built now, within capacity and dependencies.", "Exceed capacity or violate a dependency"],
    ["foundation", "coding", "Lays the whole product's data model at once, from every story's criteria.", "Invent a column no criterion needs"],
    ["data_designer", "coding", "Writes a spec the platform expands into believable demonstration data.", "Write rows or code; repeat a sentence; include ids"],
    ["developer", "coding", "Implements one story inside the scaffold, guided by the UX playbook.", "Go beyond the criteria; edit tests; use the browser's dialogs or fetch()"],
    ["tester", "coding", "Writes its own tests and assumes the code is wrong (full pack).", "Weaken an assertion to make a test pass"],
    ["reviewer", "reasoning", "Scores the increment on five weighted dimensions; the verdict is arithmetic.", "Pass work that fails its criteria"],
    ["release", "fast", "Starts the app, and writes release notes a stakeholder can read.", "Use internal component names in the notes"],
  ];

  const GATES = [
    ["clarify", "What the brief left ambiguous, where guessing wastes days", "auto", "require"],
    ["approve_vision", "Whether the platform understood the problem at all", "auto", "require"],
    ["approve_backlog", "Priority, and what is deliberately out of scope", "auto", "require"],
    ["approve_architecture", "Whether a \"build new\" verdict is acceptable", "auto", "require"],
    ["approve_sprint", "The scope of the first increment", "auto", "auto"],
    ["failed_story", "Carry on, drop the story, or stop the sprint", "auto", "require"],
    ["approve_release", "Release, release a base app, send it back, or hold", "require", "require"],
  ];
  const PACKS = {
    mvp: { repair: 3, rework: 1, tester: "off", ship: 60, weights: { "Acceptance criteria met": 45, "Operational safety": 30, "Maintainability": 15, "Reuse compliance": 5, "Test adequacy": 5 } },
    default: { repair: 5, rework: 2, tester: "on", ship: 70, weights: { "Acceptance criteria met": 35, "Test adequacy": 20, "Reuse compliance": 15, "Maintainability": 15, "Operational safety": 15 } },
  };

  const LAYERS = [
    ["Compile", "every story", "< 1 s", ["Python that does not parse, with the file and line", "A syntax error means the Developer rewrites the whole file"]],
    ["Backend checks", "every story", "< 1 s", ["A router that never creates `router`", "Routes at the root that swallow every other story's paths", "Model columns init.sql does not create", "A GET returning rows nothing seeds", "Imports that do not exist at runtime"]],
    ["Screen checks", "every story", "< 1 s", ["Calls to a path the API does not serve — the commonest cause of an empty screen", "The browser's alert/confirm instead of the UI kit", "A screen that gives up without an id", "render() using an argument it never receives", "JSX, placeholders, packages"]],
    ["Frontend check (Node)", "every story", "seconds", ["Every file parses", "Every screen imports without touching the DOM and exports title and render"]],
    ["init.sql on Postgres", "when it changes", "seconds", ["The schema really executes", "Model columns match the real tables"]],
    ["pytest in a sandbox", "full pack", "minutes", ["A throwaway container, no network, capped memory and time", "Tests that could never fail are findings for the Tester"]],
    ["API smoke run", "after all stories", "~1 min", ["Every GET against a throwaway Postgres loaded from the app's own init.sql", "A 422 that only asks for query parameters is an endpoint needing input, not a failure", "A failing path gets one repair, then is smoked again"]],
    ["Browser check", "after every deploy", "~1 min", ["Every screen opened in headless Chromium and screenshotted", "Error panels, empty screens, 'undefined' / 'null' / 'NaN' on screen", "Data fetched but not shown", "Then it uses the screen: opens a row, switches tabs, presses \"New…\""]],
    ["Review", "after deploy", "minutes", ["Five weighted dimensions and blockers", "The Reviewer sees what each screen displayed, not only the code", "The release gate cannot offer 'release' for an app that does not work"]],
  ];

  // Real events from the DupeGuard run (minutes:seconds after submission).
  const EVENTS = [
    ["00:00", 1, "analyst", "Reading the brief for gaps and contradictions"],
    ["02:41", 1, "analyst", "6 open questions; 2 contradictions found"],
    ["04:01", 3, "product_owner", "Building the product backlog"],
    ["06:41", 3, "product_owner", "1 epics, 10 stories, 54 points"],
    ["06:41", 3, "governance", "Gate 'approve_backlog' auto-approved by policy", "gate"],
    ["09:22", 5, "planner", "Sprint 1 goal: Establish the foundational data models and core duplicate detection engine to enable the first end-to-end flow of ticket intake, scanning, and dashboard visibility."],
    ["09:22", 7, "foundation", "Designing the data model for every story at once"],
    ["12:27", 7, "foundation", "Data model in place: 11 table(s) — agent, audit_entry, cluster, customer, customer_reply, duplicate_suggestion, …"],
    ["22:29", 7, "data_designer", "Demonstration data, attempt 1: cluster.first_seen is NOT NULL but 15 row(s) leave it None", "warn"],
    ["47:50", 8, "developer", "Starting S4: Run Duplicate Scan and Auto-Close", null, ["S4", "building"]],
    ["62:35", 8, "developer", "S4 is red after 3 repair attempt(s) — its tests pass, but its screen does not", "error", ["S4", "red"]],
    ["64:21", 8, "developer", "S2 is green after 0 repair attempt(s)", null, ["S2", "green"]],
    ["65:46", 8, "developer", "S1 is green after 0 repair attempt(s)", null, ["S1", "green"]],
    ["67:32", 8, "developer", "S3 is green after 0 repair attempt(s)", null, ["S3", "green"]],
    ["74:16", 8, "developer", "S9 is green after 0 repair attempt(s)", null, ["S9", "green"]],
    ["77:06", 8, "developer", "S5 is green after 1 repair attempt(s)", null, ["S5", "green"]],
    ["78:57", 8, "developer", "S6 is green after 0 repair attempt(s)", null, ["S6", "green"]],
    ["80:23", 8, "developer", "S8 is green after 0 repair attempt(s)", null, ["S8", "green"]],
    ["81:27", 8, "developer", "S7 is green after 0 repair attempt(s)", null, ["S7", "green"]],
    ["84:42", 8, "developer", "S10 is green after 1 repair attempt(s)", null, ["S10", "green"]],
    ["86:27", 8, "governance", "API smoke check: 3 GET(s) answer 500 — /api/tickets/{ticket_id}/duplicates, /api/intake/deflection, (import)", "warn"],
    ["91:07", 8, "governance", "S8: still answers 500 on /api/intake/deflection — marked red", "error", ["S8", "red"]],
    ["91:28", 9, "release", "Running at http://localhost:8114 — now opening every screen in a real browser"],
    ["91:50", 9, "release", "The browser check found 5 problem(s): Ticket Inbox: The screen shows an error: Ticket Inbox hit an error…", "error"],
    ["94:23", 10, "reviewer", "Release verdict: rework — weighted score 61.5/100 (threshold 60), 6 blockers, 2 red stories, app NOT working in the browser", "error", null, 61.5],
    ["94:45", 8, "developer", "Starting S4: Run Duplicate Scan and Auto-Close", null, ["S4", "building"]],
    ["99:09", 8, "developer", "S4 is red after 3 repair attempt(s) — its tests pass, but its screen does not", "error", ["S4", "red"]],
    ["100:59", 8, "developer", "S2 is green after 0 repair attempt(s)", null, ["S2", "green"]],
    ["102:49", 8, "developer", "S5 is green after 0 repair attempt(s)", null, ["S5", "green"]],
    ["104:40", 8, "developer", "S8 is green after 0 repair attempt(s)", null, ["S8", "green"]],
    ["107:15", 8, "governance", "S8: still answers 500 on /api/intake/deflection — marked red", "error", ["S8", "red"]],
    ["107:37", 9, "release", "Running at http://localhost:8114 — now opening every screen in a real browser"],
    ["107:58", 9, "release", "Checked in a browser: 10 screen(s), all working", "win"],
    ["111:37", 10, "reviewer", "Release verdict: rework — weighted score 90.8/100 (threshold 60), 0 blockers, 2 red stories, app working in the browser", "win", null, 90.8],
    ["111:37", 11, "governance", "The Reviewer scored this 90.8/100… every screen opened cleanly — try it before you decide. It cannot be released yet: 2 story(ies) still failing.", "gate"],
  ];

  /* ---------------------------------------------------------------- shell */
  const root = document.documentElement;
  $("#theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("poiesis-site-theme", root.dataset.theme); } catch (e) {}
  });
  const nav = $("#nav");
  addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 10), { passive: true });
  $("#menu").addEventListener("click", (e) => {
    const open = $("#navlinks").classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", String(open));
  });
  $$("#navlinks a").forEach((a) => a.addEventListener("click", () => $("#navlinks").classList.remove("open")));
  const spy = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) $$("#navlinks a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === `#${en.target.id}`));
  }), { rootMargin: "-45% 0px -50% 0px" });
  $$("main section[id]").forEach((s) => spy.observe(s));

  const reveal = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { en.target.classList.add("in"); reveal.unobserve(en.target); }
  }), { threshold: 0.12 });
  const watchReveals = () => $$(".reveal:not(.in), #gantt:not(.in)").forEach((el) => reveal.observe(el));

  document.addEventListener("pointermove", (e) => {
    const card = e.target.closest?.(".card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, { passive: true });

  function countUp(el) {
    const target = Number(el.dataset.count);
    if (reduced || !target) { el.textContent = String(target); return; }
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 1100);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  new IntersectionObserver((entries, obs) => entries.forEach((en) => {
    if (en.isIntersecting) { $$("[data-count]", en.target).forEach(countUp); obs.disconnect(); }
  }), { threshold: 0.4 }).observe($("#stats"));

  /* ---------------------------------------------------------------- the replay */
  const railStages = ["Intake", "Discovery", "Vision", "Backlog", "Architecture", "Sprint", "Scaffold", "Foundation", "Build", "Deploy", "Review", "Release", "Harvest"];
  const rail = $("#rail"), feed = $("#feed"), storiesEl = $("#stories");
  railStages.forEach((s) => rail.append(h("span", { title: s })));
  const storyEls = {};
  for (let i = 1; i <= 10; i++) storiesEl.append(storyEls[`S${i}`] = h("div", { class: "story", title: `Story S${i}` }, `S${i}`));
  const toSec = (t) => { const [m, s] = t.split(":").map(Number); return m * 60 + s; };
  let idx = 0, timer = null, playing = true, speed = 1, started = false;

  function setStage(i) {
    $$("span", rail).forEach((el, k) => { el.className = k < i ? "done" : k === i ? "now" : ""; });
    $("#stageName").textContent = railStages[i];
  }
  function show(ev) {
    const [t, stage, who, msg, tone, story, score] = ev;
    const a = AGENTS[who] || AGENTS.platform;
    setStage(stage);
    $("#stageAgent").textContent = a.name;
    $("#clock").textContent = `${String(Math.floor(toSec(t) / 60)).padStart(2, "0")}:${t.split(":")[1]}`;
    const line = h("div", { class: `ev ${tone || ""}` }, h("time", {}, t), h("span", { class: "who", style: { color: a.color } }, a.name), h("span", { class: "msg" }, msg));
    feed.append(line);
    while (feed.children.length > 14) feed.firstChild.remove();
    if (story) storyEls[story[0]].className = `story ${story[1]}`;
    if (story && story[1] === "building") $$(".story", storiesEl).forEach((el) => { if (el !== storyEls[story[0]] && el.classList.contains("building")) el.classList.remove("building"); });
    if (score) $("#score").innerHTML = `Reviewer score <b>${score}</b>`;
    if (tone === "gate" && stage === 11) $$(".story", storiesEl).forEach((el) => el.classList.remove("building"));
  }
  function reset() {
    idx = 0; feed.innerHTML = ""; $("#score").innerHTML = "Reviewer score <b>—</b>";
    Object.values(storyEls).forEach((el) => { el.className = "story"; });
    setStage(0);
  }
  function tick() {
    if (!playing) return;
    if (idx >= EVENTS.length) { timer = setTimeout(() => { reset(); tick(); }, 6000 / speed); return; }
    show(EVENTS[idx]);
    const gap = idx + 1 < EVENTS.length ? toSec(EVENTS[idx + 1][0]) - toSec(EVENTS[idx][0]) : 0;
    idx += 1;
    // A minute of the run is about half a second here; long waits are shortened.
    const ms = Math.min(2600, Math.max(650, gap * 8)) / speed;
    timer = setTimeout(tick, ms);
  }
  $("#rp-play").addEventListener("click", (e) => {
    playing = !playing;
    e.currentTarget.textContent = playing ? "❚❚ Pause" : "▶ Play";
    e.currentTarget.setAttribute("aria-label", playing ? "Pause the replay" : "Play the replay");
    if (playing) { clearTimeout(timer); tick(); }
  });
  $("#rp-restart").addEventListener("click", () => { clearTimeout(timer); reset(); playing = true; $("#rp-play").textContent = "❚❚ Pause"; tick(); });
  $("#rp-speed").addEventListener("click", (e) => { speed = speed === 1 ? 2 : speed === 2 ? 4 : 1; e.currentTarget.textContent = `${speed}×`; });
  reset();
  if (reduced) { EVENTS.forEach(show); playing = false; $("#rp-play").textContent = "▶ Play"; }
  else new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting && !started) { started = true; tick(); }
  }), { threshold: 0.3 }).observe($("#replay"));

  /* ---------------------------------------------------------------- value stream */
  const svgIcon = (d, size = 18) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("width", size); s.setAttribute("height", size); s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.9");
    s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", d); s.append(p);
    return s;
  };
  let activeStage = 0, streamAuto = true, streamTimer;
  const streamEl = $("#stream");
  STAGES.forEach((st, i) => streamEl.append(h("button", {
    class: "st", role: "tab", "aria-label": st.label,
    onclick: () => { streamAuto = false; clearInterval(streamTimer); pickStage(i); },
  }, h("span", { class: "orb" }, svgIcon(st.icon)), h("span", { class: "lbl" }, st.label),
    st.gate ? h("span", { class: `gate ${st.gate === "approve_release" ? "" : "auto"}` }, st.gate === "approve_release" ? "you decide" : "gate") : h("span", { class: "gate", style: { visibility: "hidden" } }, "·"))));
  function pickStage(i) {
    activeStage = i;
    $$(".st", streamEl).forEach((el, k) => { el.classList.toggle("on", k === i); el.classList.toggle("passed", k < i); el.setAttribute("aria-selected", String(k === i)); });
    const st = STAGES[i];
    const agents = st.agents.map((k) => h("span", { class: "agent-chip" }, h("i", { style: { background: AGENTS[k].color } }, AGENTS[k].initials), AGENTS[k].name));
    const detail = $("#stageDetail");
    detail.innerHTML = "";
    detail.append(
      h("div", { class: "sd-main fade-swap" },
        h("div", { class: "sd-num" }, `Stage ${String(i + 1).padStart(2, "0")} of 13`),
        h("h3", {}, st.label),
        agents.length ? h("div", {}, agents) : h("div", { class: "muted", style: { fontSize: "14.5px" } }, "Run by the platform itself — no agent"),
        h("dl", { class: "sd-rows" },
          h("dt", {}, "Reads"), h("dd", {}, st.reads),
          h("dt", {}, "Produces"), h("dd", {}, st.produces),
          h("dt", {}, "Gate"), h("dd", {}, st.gate ? h("code", {}, st.gate) : "none", st.gate === "approve_release" ? " — never automatic" : st.gate ? " — automatic or yours, by pack" : ""))),
      h("div", { class: "sd-side fade-swap" },
        h("div", { class: "lab" }, "In the DupeGuard run"),
        h("blockquote", {}, st.example),
        h("p", { class: "hint", style: { marginTop: "16px" } }, "Every stage writes a typed artifact and emits events; every model call is kept with its prompt and reply.")));
  }
  pickStage(0);
  if (!reduced) {
    new IntersectionObserver((entries, obs) => entries.forEach((en) => {
      if (en.isIntersecting && streamAuto) {
        streamTimer = setInterval(() => { if (streamAuto) pickStage((activeStage + 1) % STAGES.length); }, 3200);
        obs.disconnect();
      }
    }), { threshold: 0.4 }).observe(streamEl);
  }

  /* ---------------------------------------------------------------- agents */
  const grid = $("#agentGrid");
  AGENT_CARDS.forEach(([key, role, does, refuses], i) => {
    const a = AGENTS[key];
    const card = h("button", { class: "agent reveal", style: { "--c": a.color, transitionDelay: `${i * 40}ms` }, "aria-label": `${a.name}: ${does} Refuses to: ${refuses}`,
      onclick: (e) => e.currentTarget.classList.toggle("flip") },
      h("div", { class: "agent-inner" },
        h("div", { class: "face" }, h("div", { class: "avatar" }, a.initials), h("h4", {}, a.name), h("div", { class: "role" }, `${role} model`), h("p", {}, does), h("div", { class: "flip-hint" }, "Refuses to… ↻")),
        h("div", { class: "face back" }, h("div", { class: "avatar" }, a.initials), h("h4", {}, a.name),
          h("div", { class: "refuse" }, h("b", {}, "Refuses to"), refuses))));
    grid.append(card);
  });

  /* ---------------------------------------------------------------- governance */
  const gateList = $("#gateList");
  const gateRows = GATES.map(([key, what]) => {
    const mode = h("span", { class: "mode" });
    gateList.append(h("div", { class: "gaterow reveal" }, h("code", {}, key), h("span", {}, what), mode));
    return mode;
  });
  function setPack(name, first) {
    const p = PACKS[name];
    $$(".pack-toggle button").forEach((b) => { const on = b.dataset.pack === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    GATES.forEach((g, i) => { const m = name === "mvp" ? g[2] : g[3]; gateRows[i].className = `mode ${m}`; gateRows[i].textContent = m === "require" ? "you decide" : "automatic"; });
    for (const [id, v] of [["p-repair", p.repair], ["p-rework", p.rework], ["p-tester", p.tester], ["p-ship", p.ship]]) {
      const el = $(`#${id}`);
      const b = $("b", el);
      if (!first && b.textContent !== String(v)) { el.classList.add("changed"); setTimeout(() => el.classList.remove("changed"), 900); }
      b.textContent = String(v);
    }
    const w = $("#weights");
    if (first) w.innerHTML = "";
    Object.entries(p.weights).forEach(([k, v], i) => {
      let row = w.children[i];
      if (!row) { row = h("div", {}, h("span", {}, h("span", { class: "wl" }), h("div", { class: "bar" }, h("i"))), h("b", {})); w.append(row); }
      $(".wl", row).textContent = k;
      $("b", row).textContent = `${v}%`;
      requestAnimationFrame(() => { $("i", row).style.width = `${v * 2}%`; });
    });
  }
  $$(".pack-toggle button").forEach((b) => b.addEventListener("click", () => setPack(b.dataset.pack)));
  setPack("mvp", true);

  /* ---------------------------------------------------------------- verification */
  const layersEl = $("#layers");
  function pickLayer(i) {
    $$(".layer", layersEl).forEach((el, k) => el.classList.toggle("on", k === i));
    const [name, when, time, items] = LAYERS[i];
    const card = $("#layerDetail");
    card.innerHTML = "";
    card.append(h("div", { class: "fade-swap" },
      h("div", { class: "sd-num" }, `Layer ${i + 1} of 9 · ${when} · ${time}`),
      h("h3", { style: { fontSize: "24px", marginTop: "6px" } }, name),
      h("ul", {}, items.map((t) => h("li", { html: t.replace(/`([^`]+)`/g, "<code>$1</code>") }))),
      i === 6 || i === 2 ? h("div", { class: "lesson" }, h("b", {}, "Learned the hard way. "),
        "A check that flags something the Developer cannot change turns a working story red after every repair. Three such false positives were found in one run and fixed — each now has a self-test.") : null));
  }
  LAYERS.forEach(([name, when, time], i) => layersEl.append(h("button", { class: "layer reveal", onclick: () => pickLayer(i), onmouseenter: () => pickLayer(i) },
    h("span", { class: "n" }, String(i + 1)), h("span", { class: "t" }, name), h("span", { class: "w" }, when))));
  pickLayer(7);

  /* ---------------------------------------------------------------- architecture */
  const VIEWS = {
    platform: {
      groups: [{ x: 230, y: 118, w: 520, h: 258, label: "Orchestrator · FastAPI + LangGraph" }],
      nodes: [
        ["stakeholder", 20, 28, 175, 62, "Stakeholder", "one user", "#eb1000", "The business stakeholder: the only human seat. Submits a brief, documents and links; answers typed gates; decides the release.", "Browser", ["Sees evidence, not promises: the app is running before the release decision", "Every answer is recorded with an actor"]],
        ["ui", 260, 28, 200, 62, "Control room", "Next.js · :3000", "#0265dc", "Runs, gates, the running apps, boards, codebase maps, the portfolio and observability — live over a WebSocket.", "Next.js 14 · Tailwind (Spectrum) · Mermaid", ["Home: brief, attachments, the ten agents", "Run page: stage rail, gate, app, traces, activity", "Boards, Codebases, Portfolio, Observability"]],
        ["graph", 250, 152, 230, 60, "Value stream graph", "13 nodes · typed gates", "#5258E4", "The run as a LangGraph graph, checkpointed in Postgres after every node, so it survives restarts and waits on gates indefinitely.", "LangGraph · Postgres checkpointer", ["Gates are interrupts with a schema and a default", "Every non-deterministic step is memoised: a replay never re-spends a model call"]],
        ["engine", 500, 152, 230, 60, "Engine", "one driver · a queue", "#5258E4", "Drives one run at a time by default and queues the rest; resumes in-flight runs after a restart.", "asyncio", ["POIESIS_MAX_CONCURRENT_RUNS", "Cancel and retry from the last checkpoint"]],
        ["agents", 250, 228, 150, 60, "Agents ×10", "schema-bound", "#8A3FD6", "Ten agents, one prompt each, a typed JSON output decoded against its schema.", "prompts/*.md · agents/schemas.py", ["Thinking on for the judges, off for the writers", "The Developer's prompt includes the UX playbook"]],
        ["checks", 415, 228, 150, 60, "Checks", "static · smoke · browser", "#007A4D", "Nine layers of verification between the model's code and a person.", "Python AST · Node · Postgres · Playwright", ["Findings go back as instructions naming the file", "A real browser opens and uses every screen"]],
        ["codemap", 580, 228, 150, 60, "Code maps", "ArchiLens", "#0FB5AE", "Every generated codebase drawn: topology, modules by story, data model, request flows.", "ArchiLens 0.2.0 · Mermaid", ["Poiesis supplies the module graph", "The local model writes summaries and flows"]],
        ["gate", 250, 304, 230, 56, "Model gate", "one local call at a time", "#F68511", "Every model call, from any agent or feature, passes one gate, so the GPU never serves two contexts at once.", "llm.py · native Ollama client", ["Schema-constrained decoding", "Streaming with an idle timeout", "A reply that thinks its budget away is retried without"]],
        ["telemetry", 500, 304, 230, 56, "Telemetry", "spans · traces · metrics", "#1D6F8C", "Every model call kept with prompt and reply; every stage, sandbox run and deploy timed.", "OpenTelemetry · Prometheus client", ["A run's cost is a query", "Traces to Jaeger, metrics to Prometheus"]],
        ["ollama", 20, 176, 175, 72, "Ollama", "qwen3.6 35B-A3B · GPU", "#76b900", "The models, on the host GPU: reasoning, coding and fast roles, embeddings and vision.", "Ollama · Qwen3.6 35B-A3B · nomic-embed · gemma4", ["Mixture of experts: 3B active of 35B", "Started by restart-ollama.ps1 with 1.5 GB kept for the display"]],
        ["plane", 790, 28, 190, 60, "Plane", "a board per idea", "#4046CA", "Every idea its own project: epics as modules, stories as work items, the sprint as a cycle; cards move as stories pass.", "Plane v1.4.2, self-hosted", ["Never stops a run; never duplicates", "Jira Cloud mirrored the same way when configured"]],
        ["git", 790, 108, 190, 60, "Git remote", "branch · tag · PR", "#6E6E6E", "Branch run/<id> pushed after the scaffold and every story; a tag and a pull request at release.", "GitPython · GitHub API", ["One repository per product by default"]],
        ["observ", 790, 188, 190, 60, "Jaeger · Grafana", "Prometheus", "#DE3D82", "The long history: trace trees per run, and a provisioned platform dashboard.", "Jaeger · Prometheus · Grafana", ["The console's Observability page reads the same records"]],
        ["indexer", 790, 300, 190, 60, "Indexer", "repos → graph", "#B130BD", "Scans your existing repositories into components, capabilities and technologies.", "tree-sitter · GitPython", ["Reuse can only be as good as the portfolio indexed"]],
        ["postgres", 20, 416, 175, 64, "Postgres", "checkpoints · traces", "#336791", "Runs, artifacts, gates, events, checkpoints, model calls and spans.", "Postgres 16", ["Artifacts are JSON columns", "Checkpoints make gates durable"]],
        ["redis", 210, 416, 140, 64, "Redis", "live events", "#D82C20", "Agent narration fans out to every open run page.", "Redis pub/sub · WebSocket", []],
        ["neo4j", 365, 416, 180, 64, "Neo4j", "portfolio graph", "#018BFF", "Projects, components, capabilities, decisions, stories, lessons and reuse edges.", "Neo4j 5 · full-text", ["The Architect must ask it before designing"]],
        ["qdrant", 560, 416, 170, 64, "Qdrant", "recall by meaning", "#DC244C", "The same knowledge, embedded, so recall works by meaning as well as by word.", "Qdrant · nomic-embed-text", []],
        ["sandbox", 20, 530, 220, 64, "Docker sandbox", "throwaway · no network", "#2496ED", "Generated code never runs in the orchestrator: throwaway containers with capped memory, CPU, pids and time.", "Docker via the socket", ["A sibling container, so the host path is configured and proved"]],
        ["workspace", 255, 530, 200, 64, "Workspace", "a git repo per run", "#6E6E6E", "Every run's code in its own repository; commits are the build's audit trail.", "git", ["One commit per story and repair"]],
        ["apps", 470, 530, 260, 64, "Generated apps", "gateway · api · data · db", "#0265dc", "Each run's app as its own Compose project on 127.0.0.1:81xx, restored after a reboot.", "Docker Compose · nginx · FastAPI · Postgres", ["See the 'A generated app' view"]],
      ],
      edges: [["stakeholder", "ui"], ["ui", "graph", "flow"], ["graph", "engine"], ["graph", "agents"], ["agents", "gate", "flow"], ["gate", "ollama", "flow"],
        ["graph", "plane"], ["graph", "git"], ["telemetry", "observ", "flow"], ["engine", "postgres"], ["engine", "redis", "flow"], ["redis", "ui"],
        ["agents", "neo4j"], ["neo4j", "qdrant"], ["indexer", "neo4j"], ["checks", "sandbox"], ["checks", "apps", "flow"], ["codemap", "workspace"], ["agents", "workspace", "flow"], ["workspace", "git"], ["telemetry", "postgres"]],
    },
    app: {
      groups: [{ x: 240, y: 130, w: 560, h: 380, label: "One Compose project per run" }],
      nodes: [
        ["visitor", 30, 280, 170, 70, "Visitor", "a browser", "#eb1000", "Opens the app on 127.0.0.1 — model-written code stays off the network until access control exists.", "Any modern browser", []],
        ["gateway", 270, 270, 200, 90, "Gateway", "nginx · the UI · /api", "#222222", "Serves the screens, routes /api to the api service, and falls back to the data service when the api is down. Resolves services per request.", "nginx · resolver 127.0.0.11", ["Waits for the database and data service, not for the api", "restart: unless-stopped"]],
        ["api", 560, 160, 220, 80, "api service", "story endpoints + data API", "#4046CA", "The story routers plus the generic data API. A router that fails to import is left out and reported, instead of taking the api down.", "FastAPI · SQLAlchemy", ["/api/platform/modules lists broken modules", "Story paths win over generic ones"]],
        ["data", 560, 400, 220, 80, "data service", "generic data API only", "#7E84FA", "No story code at all: every table served for list, read, create, update and delete, so screens keep their data even when a story breaks.", "FastAPI (app.data_main)", ["?q=, ?column=value, ?sort=-column, paging", "A filter on a missing column is a 422"]],
        ["db", 850, 270, 130, 90, "Postgres", "seeded from init.sql", "#F68511", "The schema and the demonstration data, loaded once on a fresh volume.", "Postgres 16", ["A fresh deploy resets a demo"]],
        ["shell", 270, 150, 200, 70, "Shell & UI kit", "platform-owned", "#0265dc", "Navigation, command palette, themes, skeletons, and the components every screen composes: stats, charts, tables with drawers, boards, dialogs.", "app.js · ui.js · styles.css", ["The Developer composes; it does not draw"]],
        ["probe", 270, 420, 200, 70, "Browser check", "opens and uses every screen", "#007A4D", "After every deploy: every screen opened, a row opened, tabs switched, 'New…' pressed; errors and screenshots recorded.", "Playwright · Chromium", []],
      ],
      edges: [["visitor", "gateway", "flow"], ["gateway", "api", "flow"], ["gateway", "data"], ["api", "db", "flow"], ["data", "db"], ["shell", "gateway"], ["probe", "gateway", "flow"]],
    },
    loop: { loop: true, nodes: [
      ["run", "A run", "brief → app", "#0265dc", "A brief goes through the value stream to a verified increment.", ["Stories, decisions and outcomes recorded as it goes"]],
      ["harvest", "Harvest", "what it built and learned", "#0D8A80", "Capabilities, technologies, stories, architecture decisions and the outcome go back into the graph.", ["One lesson per failed or repaired story"]],
      ["graph", "Graph + vectors", "by word and by meaning", "#018BFF", "Neo4j holds the structure; Qdrant the same knowledge by meaning.", ["Your indexed portfolio is already there"]],
      ["recall", "Recall", "before any design", "#8A3FD6", "The Architect must query what exists before it designs; the Developer is shown the lessons that apply before it writes.", ["Reuse verdicts: reuse, extend, or build new with a rationale"]],
      ["better", "A better next run", "reuse compounds", "#eb1000", "Build quality and reuse quality both compound with usage — the part a competitor cannot copy with better prompts.", []],
    ] },
  };

  const svg = $("#archSvg");
  const NS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
  let currentView = "platform";

  function detail(name, tech, text, bullets, color) {
    const card = $("#archDetail");
    card.innerHTML = "";
    card.append(h("div", { class: "fade-swap" },
      h("h3", {}, h("span", { style: { width: "12px", height: "12px", borderRadius: "4px", background: color, display: "inline-block" } }), name),
      tech ? h("div", { class: "tech" }, tech) : null,
      h("p", { style: { margin: 0, color: "var(--ink-2)", fontSize: "15.5px" } }, text),
      bullets && bullets.length ? h("ul", {}, bullets.map((b) => h("li", {}, b))) : null,
      h("p", { class: "hint" }, "Hover or tap another box.")));
  }

  function anchor(a, b) {
    const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 }, bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    const dx = bc.x - ac.x, dy = bc.y - ac.y;
    if (Math.abs(dx) > Math.abs(dy) * 1.2) {
      const s = { x: dx > 0 ? a.x + a.w : a.x, y: ac.y }, e = { x: dx > 0 ? b.x : b.x + b.w, y: bc.y };
      const mx = (s.x + e.x) / 2;
      return `M${s.x},${s.y} C${mx},${s.y} ${mx},${e.y} ${e.x},${e.y}`;
    }
    const s = { x: ac.x, y: dy > 0 ? a.y + a.h : a.y }, e = { x: bc.x, y: dy > 0 ? b.y : b.y + b.h };
    const my = (s.y + e.y) / 2;
    return `M${s.x},${s.y} C${s.x},${my} ${e.x},${my} ${e.x},${e.y}`;
  }

  function drawView(name) {
    currentView = name;
    const v = VIEWS[name];
    svg.innerHTML = "";
    svg.append(sv("defs", {}));
    $("defs", svg).innerHTML = '<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>';
    if (v.loop) return drawLoop(v);
    const byId = {};
    v.nodes.forEach(([id, x, y, w, hh]) => { byId[id] = { x, y, w, h: hh }; });
    (v.groups || []).forEach((g) => {
      const grp = sv("g", { class: "group" });
      grp.append(sv("rect", { x: g.x, y: g.y, width: g.w, height: g.h, rx: 16 }));
      const t = sv("text", { x: g.x + 14, y: g.y + 20 }); t.textContent = g.label; grp.append(t);
      svg.append(grp);
    });
    const edgeEls = v.edges.map(([a, b, kind]) => {
      const p = sv("path", { d: anchor(byId[a], byId[b]), class: `edge ${kind === "flow" ? "flow" : ""}` });
      p.dataset.a = a; p.dataset.b = b;
      svg.append(p);
      return p;
    });
    const nodeEls = v.nodes.map(([id, x, y, w, hh, title, sub, color, text, tech, bullets], i) => {
      const g = sv("g", { class: "node", tabindex: 0, role: "button", "aria-label": `${title}: ${text}` });
      g.append(sv("rect", { class: "box", x, y, width: w, height: hh, rx: 12 }));
      g.append(sv("rect", { x, y: y + 12, width: 4, height: hh - 24, rx: 2, fill: color }));
      const t1 = sv("text", { x: x + 18, y: y + hh / 2 - 3 }); t1.textContent = title; g.append(t1);
      const t2 = sv("text", { x: x + 18, y: y + hh / 2 + 15, class: "sub" }); t2.textContent = sub; g.append(t2);
      const pip = sv("circle", { class: "pip", cx: x + w - 14, cy: y + 14, r: 4, fill: color }); g.append(pip);
      const focus = () => {
        $$(".node", svg).forEach((n) => n.classList.remove("on"));
        g.classList.add("on");
        const linked = new Set([id]);
        edgeEls.forEach((e) => {
          const hit = e.dataset.a === id || e.dataset.b === id;
          e.classList.toggle("hot", hit); e.classList.toggle("dim", !hit);
          if (hit) { linked.add(e.dataset.a); linked.add(e.dataset.b); }
        });
        nodeEls.forEach((n) => n.el.classList.toggle("dim", !linked.has(n.id)));
        detail(title, tech, text, bullets, color);
      };
      g.addEventListener("mouseenter", focus); g.addEventListener("focus", focus); g.addEventListener("click", focus);
      if (!reduced) { g.style.opacity = "0"; g.style.transition = "opacity .5s"; setTimeout(() => { g.style.opacity = ""; }, 60 + i * 45); }
      svg.append(g);
      return { id, el: g, focus };
    });
    svg.onmouseleave = () => { edgeEls.forEach((e) => e.classList.remove("hot", "dim")); nodeEls.forEach((n) => n.el.classList.remove("dim")); };
    nodeEls[name === "platform" ? 2 : 1].focus();
  }

  function drawLoop(v) {
    const cx = 500, cy = 320, r = 225, n = v.nodes.length;
    const pos = v.nodes.map((_, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }; });
    const ring = sv("circle", { cx, cy, r, class: "edge flow", fill: "none" }); svg.append(ring);
    const core = sv("g", {});
    core.append(sv("circle", { cx, cy, r: 100, fill: "var(--accent-soft)", stroke: "var(--accent)", "stroke-width": 1.5 }));
    const c1 = sv("text", { x: cx, y: cy - 4, "text-anchor": "middle", style: "font: 700 22px var(--sans); fill: var(--ink)" }); c1.textContent = "Compounding";
    const c2 = sv("text", { x: cx, y: cy + 20, "text-anchor": "middle", style: "font: 500 13px var(--sans); fill: var(--muted)" }); c2.textContent = "each run improves the next";
    core.append(c1, c2); svg.append(core);
    const els = v.nodes.map(([id, title, sub, color, text, bullets], i) => {
      const { x, y } = pos[i];
      const g = sv("g", { class: "node", tabindex: 0, role: "button", "aria-label": `${title}: ${text}` });
      g.append(sv("rect", { class: "box", x: x - 100, y: y - 34, width: 200, height: 68, rx: 14 }));
      g.append(sv("rect", { x: x - 100, y: y - 22, width: 4, height: 44, rx: 2, fill: color }));
      const t1 = sv("text", { x: x - 82, y: y - 3 }); t1.textContent = title; g.append(t1);
      const t2 = sv("text", { x: x - 82, y: y + 15, class: "sub" }); t2.textContent = sub; g.append(t2);
      const focus = () => { $$(".node", svg).forEach((m) => m.classList.remove("on")); g.classList.add("on"); detail(title, "", text, bullets, color); };
      g.addEventListener("mouseenter", focus); g.addEventListener("focus", focus); g.addEventListener("click", focus);
      svg.append(g);
      return focus;
    });
    if (!reduced) {
      const dot = sv("circle", { r: 7, fill: "var(--brand)" });
      svg.append(dot);
      let t0 = performance.now();
      const spin = (t) => {
        if (currentView !== "loop") return;
        const a = -Math.PI / 2 + ((t - t0) / 9000) * 2 * Math.PI;
        dot.setAttribute("cx", cx + r * Math.cos(a)); dot.setAttribute("cy", cy + r * Math.sin(a));
        requestAnimationFrame(spin);
      };
      requestAnimationFrame(spin);
    }
    els[0]();
  }
  $$("#architecture .tabs button").forEach((b) => b.addEventListener("click", () => {
    $$("#architecture .tabs button").forEach((x) => x.classList.toggle("on", x === b));
    drawView(b.dataset.view);
  }));
  drawView("platform");

  /* ---------------------------------------------------------------- product tour */
  const TOUR = [
    ["console-home", "The control room", "Describe the problem, attach what you have", "localhost:3000", "Describe the problem, attach documents and links, and watch the agents pick it up. The value stream shows where the run is and where it will stop for you."],
    ["board", "Boards", "Every idea as a Kanban board", "localhost:3000/runs/7fdad83a…/board", "Every idea's backlog as a board in a self-hosted Plane: modules, work items with priorities and points, a sprint cycle — cards move as the agents build."],
    ["codemap-modules", "Codebase maps", "Every app drawn by ArchiLens", "localhost:3000/runs/7fdad83a…/codebase", "Screens and APIs grouped by the story they deliver, with the HTTP calls between them. Click a box for its summary, calls, endpoints and files."],
    ["codemap-flow", "Request flows", "Traced by the local model", "localhost:3000/runs/7fdad83a…/codebase", "A sequence diagram for every story endpoint, from the request to the database — written by the local model through ArchiLens."],
    ["observability", "Observability", "Where the time and the GPU go", "localhost:3000/observability", "Dependency health, model calls and tokens over time, response-time percentiles, GPU busy, model time by agent, and errors grouped by run."],
    ["portfolio", "Portfolio recall", "What already exists", "localhost:3000/knowledge", "The same recall the Architect and Developer use: components by word and by meaning, past stories with their outcome, lessons and decisions."],
    ["dupeguard-scan", "DupeGuard · Scan now", "What it built", "localhost:8114/#/duplicate_scan", "The generated app: 22 new tickets scanned — same-customer chasers closed at 97.5 and 99, outage reports linked through known issues, uncertain pairs sent to review, each with its rule."],
    ["dupeguard-intake", "DupeGuard · Deflection", "Prevention at intake", "localhost:8114/#/ticket_intake", "As a customer types, an active known issue is recognised and its message shown before a duplicate ticket is ever raised."],
  ];
  const list = $("#tourList"), img = $("#tourImg");
  let tourIdx = 0, tourTimer;
  function pickTour(i, user) {
    tourIdx = i;
    $$(".tour-item", list).forEach((el, k) => el.classList.toggle("on", k === i));
    const [file, , , url, cap] = TOUR[i];
    img.classList.add("out");
    setTimeout(() => { img.onload = () => img.classList.remove("out"); img.src = `assets/${file}.webp`; img.alt = TOUR[i][1]; }, 220);
    $("#tourUrl").textContent = url;
    $("#tourCaption").textContent = cap;
    clearTimeout(tourTimer);
    if (!user && !reduced) tourTimer = setTimeout(() => pickTour((tourIdx + 1) % TOUR.length), 7000);
  }
  TOUR.forEach(([, title, sub], i) => list.append(h("button", { class: "tour-item", onclick: () => pickTour(i, true) }, h("b", {}, title), h("span", {}, sub), h("div", { class: "prog" }, h("i")))));
  TOUR.forEach(([file]) => { const pre = new Image(); pre.src = `assets/${file}.webp`; });
  new IntersectionObserver((entries, obs) => entries.forEach((en) => { if (en.isIntersecting) { pickTour(0); obs.disconnect(); } }), { threshold: 0.3 }).observe(list);

  /* ---------------------------------------------------------------- the run's timeline */
  const GANTT = [
    ["Planning", 0, 9.4, "#5258E4", "9 min"], ["Foundation", 9.4, 47.8, "#0D8A80", "38 min"], ["Build", 47.8, 84.7, "#0265DC", "37 min"],
    ["API smoke", 84.7, 91.5, "#F68511", "7 min"], ["Deploy + browser", 91.5, 91.9, "#007A4D", "< 1"], ["Review", 91.9, 94.4, "#1D6F8C", "3 min"],
    ["Rework round", 94.4, 107.6, "#DE3D82", "13 min"], ["Deploy + browser", 107.6, 108, "#007A4D", "< 1"], ["Review", 108, 111.6, "#1D6F8C", "4 min"],
  ];
  const rows = $("#ganttRows");
  GANTT.forEach(([label, a, b, color, dur], i) => rows.append(h("div", { class: "g-row" },
    h("span", { class: "g-l" }, label),
    h("div", { class: "g-track" }, h("div", { class: "g-bar", style: { left: `${(a / 112) * 100}%`, width: `${Math.max(0.8, ((b - a) / 112) * 100)}%`, "--c": color, transitionDelay: `${i * 90}ms` } })),
    h("span", { class: "g-t" }, dur))));

  /* ---------------------------------------------------------------- stack and docs */
  const STACK = [
    ["Orchestration", [["FastAPI", "#009688"], ["LangGraph", "#1C3C3C"], ["Postgres", "#336791"], ["Redis", "#D82C20"], ["asyncio", "#3776AB"]]],
    ["Models", [["Ollama", "#76b900"], ["Qwen3.6 35B-A3B", "#5258E4"], ["nomic-embed-text", "#0FB5AE"], ["gemma4 (vision)", "#4285F4"], ["LiteLLM (hosted)", "#8A3FD6"]]],
    ["Knowledge & code", [["Neo4j", "#018BFF"], ["Qdrant", "#DC244C"], ["tree-sitter", "#6E6E6E"], ["ArchiLens", "#0FB5AE"], ["GitPython", "#F05032"]]],
    ["Delivery & insight", [["Docker", "#2496ED"], ["Playwright", "#2EAD33"], ["Next.js", "#111111"], ["Plane", "#3F76FF"], ["OpenTelemetry", "#F5A800"], ["Prometheus · Grafana", "#E6522C"]]],
  ];
  const sg = $("#stackGroups");
  STACK.forEach(([title, items]) => sg.append(h("div", { class: "reveal" }, h("h4", {}, title), h("div", { class: "stack" }, items.map(([n, c]) => h("span", { class: "chip", style: { "--c": c } }, h("i"), n))))));

  const DOCS = [
    ["SETUP-WINDOWS", "Setup", "Install on a GPU laptop"], ["FIRST-RUN", "First run", "Brief to running app"], ["OPERATIONS", "Operations", "Start, check, repair"],
    ["ARCHITECTURE", "Architecture", "Design positions"], ["AGENTS", "Agents", "Contracts and prompts"], ["CHECKS", "Verification", "Every check, and why"],
    ["API", "API", "Script the platform"], ["CODEMAPS", "Code maps", "The ArchiLens integration"], ["PLANE", "Boards", "Plane, self-hosted"], ["CASE-STUDY-DUPEGUARD", "Case study", "One run, honestly"],
  ];
  const docs = $("#docs");
  DOCS.forEach(([file, title, sub]) => docs.append(h("a", { class: "doc reveal", href: `https://github.com/saurabh-oss/poiesis/blob/main/docs/${file}.md` }, h("b", {}, title), h("span", {}, sub))));

  $$(".copy").forEach((b) => b.addEventListener("click", async () => {
    const text = b.parentElement.innerText.replace(/^Copy\n?/, "").replace(/\s+#.*$/gm, "").trim();
    try { await navigator.clipboard.writeText(text); b.textContent = "Copied"; } catch (e) { b.textContent = "Select and copy"; }
    setTimeout(() => { b.textContent = "Copy"; }, 1600);
  }));

  watchReveals();
})();
