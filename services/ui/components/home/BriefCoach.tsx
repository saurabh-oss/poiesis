"use client";

import Icon from "../Icon";

/**
 * The four things the Analyst asks about when a brief leaves them out. Word
 * matching is only a nudge, not a judgement, but it shows while you type what
 * the Analyst will otherwise have to ask you later.
 */
const CHECKS = [
  { key: "who", label: "Who is affected", test: /\b(users?|customers?|candidates?|staff|team|employees?|managers?|recruiters?|people|patients?|students?|visitors?|clients?|colleagues|admins?|anyone|everyone)\b/i },
  { key: "problem", label: "What goes wrong today", test: /\b(lose|losing|lost|lose track|can'?t|cannot|slow|manual|errors?|problems?|pain|drop|missing|broken|confus\w*|waste|delay\w*|email|paper|spreadsheet|no (simple|easy|way))\b/i },
  { key: "constraint", label: "What must stay true", test: /\b(must|legal|policy|compliance|gdpr|only|never|limit|security|privacy|budget|deleted?|retain|no approval|no login)\b/i },
  { key: "when", label: "When it matters", test: /\b(before|deadline|asap|urgent|week|month|quarter|q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december|20\d\d)\b/i },
];

export default function BriefCoach({ text }: { text: string }) {
  const trimmed = text.trim();
  const words = trimmed ? trimmed.split(/\s+/).length : 0;
  const hits = CHECKS.map((c) => ({ ...c, ok: c.test.test(text) }));
  const score = hits.filter((h) => h.ok).length;

  return (
    <div className="mt-2.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {hits.map((h) => (
          <span
            key={h.key}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] transition-colors duration-300 ${
              h.ok ? "border-moss/40 bg-moss/[0.07] text-moss" : "border-rule text-graphite"
            }`}
          >
            {h.ok ? <Icon name="check" size={11} strokeWidth={2.6} className="pop" /> : <span className="h-1.5 w-1.5 rounded-full bg-rule" />}
            {h.label}
          </span>
        ))}
        <span className="ml-auto font-mono text-[11px] tabular-nums text-graphite">{words} words</span>
      </div>
      {trimmed && (
        <p className="text-[11.5px] text-graphite">
          {score === 4
            ? "That covers what the Analyst usually has to ask about."
            : `Briefs that cover all four usually get fewer questions from the Analyst. ${4 - score} to go.`}
        </p>
      )}
    </div>
  );
}
