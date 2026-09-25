"use client";

import { useEffect, useState } from "react";
import { api, type DomainLayer } from "@/lib/api";
import Icon from "./Icon";

/** An enterprise run's business logic: its roles, its lifecycles, and every rule with its tests. */
export default function DomainCard({ runId, active }: { runId: string; active: boolean }) {
  const [d, setD] = useState<DomainLayer | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => api.runDomain(runId).then((r) => alive && setD(r)).catch(() => {});
    void load();
    const t = active ? setInterval(load, 20000) : undefined;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [runId, active]);

  if (!d) return null;
  const t = d.tests || {};
  const untested = new Set(t.untested || []);
  const rules = open ? d.rules : d.rules.slice(0, 6);
  return (
    <div className="overflow-hidden rounded border border-rule bg-paper shadow-spectrum">
      <div className="flex items-center gap-2 px-4 py-2.5">
        <Icon name="check" size={14} className="text-signal" />
        <p className="text-[13px] font-medium">Business logic</p>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold ${
          !d.imports ? "bg-[#FFEBE9] text-[#D31510]" : t.failed ? "bg-[#FFF4E5] text-[#B35F00]" : "bg-[#E6F6EF] text-[#007A4D]"}`}>
          {!d.imports ? "did not import" : t.total ? `${t.passed}/${t.total} rule tests` : "no tests"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-1 border-y border-rule px-3 py-2.5 text-center">
        {[["Rules", d.rules.length], ["Workflows", d.workflows.length], ["Roles", Object.keys(d.roles || {}).length]].map(([l, v]) => (
          <div key={l as string}>
            <p className="text-[15px] font-semibold leading-none">{v as number}</p>
            <p className="mt-0.5 text-[10.5px] text-graphite">{l}</p>
          </div>
        ))}
      </div>
      <ul className="divide-y divide-rule">
        {rules.map((r) => (
          <li key={r.id} className="flex items-start gap-2 px-4 py-2">
            <span className="mt-0.5 shrink-0 rounded bg-[#F5F9FF] px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-signal">{r.id}</span>
            <span className="min-w-0 flex-1 text-[12.5px] leading-snug">{r.title}
              <span className="block text-[10.5px] text-graphite">{r.kind}{r.source ? ` · ${r.source}` : ""}</span></span>
            {untested.has(r.id)
              ? <span title="No test is named after this rule" className="mt-0.5 text-[10.5px] text-[#B35F00]">untested</span>
              : <Icon name="check" size={12} className="mt-1 text-[#007A4D]" />}
          </li>
        ))}
      </ul>
      {d.rules.length > 6 && (
        <button onClick={() => setOpen(!open)} className="w-full border-t border-rule px-4 py-2 text-left text-[12px] text-signal hover:bg-mist">
          {open ? "Show fewer" : `All ${d.rules.length} rules`}
        </button>
      )}
      {d.workflows.length > 0 && (
        <div className="space-y-2 border-t border-rule px-4 py-3">
          {d.workflows.map((w) => (
            <div key={w.name}>
              <p className="text-[12px] font-medium">{w.entity.replace(/_/g, " ")} lifecycle</p>
              <p className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-graphite">
                {w.states.map((s, i) => (
                  <span key={s} className="flex items-center gap-1">{i > 0 && <span>→</span>}
                    <span className="rounded bg-mist px-1.5 py-0.5 font-mono">{s}</span></span>
                ))}
              </p>
            </div>
          ))}
        </div>
      )}
      {d.problems?.length > 0 && (
        <p className="border-t border-rule px-4 py-2 text-[11.5px] text-[#B35F00]">{d.problems.length} problem(s) remained after the domain stage</p>
      )}
    </div>
  );
}
