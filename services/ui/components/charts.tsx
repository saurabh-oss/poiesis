"use client";

import { useEffect, useState } from "react";

/** Small SVG charts in the Spectrum palette, animated on first draw. */

export const PALETTE = ["#0FB5AE", "#4046CA", "#F68511", "#DE3D82", "#7E84FA", "#72E06A", "#147AF3", "#7326D3", "#E8C600", "#CB5D00"];

export function colorFor(key: string): string {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function CountUp({ value, format }: { value: number; format?: (n: number) => string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const from = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 900);
      setN(from + (value - from) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{format ? format(n) : Math.round(n).toLocaleString()}</>;
}

export function Sparkline({ values, color = "#0265DC", height = 34, width = 120 }: {
  values: number[]; color?: string; height?: number; width?: number;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => [i * step, height - 3 - (v / max) * (height - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const id = `sg${color.replace("#", "")}${values.length}`;
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="overflow-visible">
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity=".28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} className="chart-fade" />
      <path d={line} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round"
            vectorEffect="non-scaling-stroke" className="chart-draw" pathLength={1} />
    </svg>
  );
}

export function Ring({ value, size = 64, color = "#0265DC", label }: { value: number; size?: number; color?: string; label?: string }) {
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label ?? `${v}%`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#EDEDED" strokeWidth={6} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={6} strokeLinecap="round"
              strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`}
              className="ring-draw" style={{ ["--circ" as any]: c }} />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fontSize={size * 0.24} fontWeight={600} fill="#2C2C2C">
        {Math.round(v)}%
      </text>
    </svg>
  );
}

export function Donut({ items, size = 150, thickness = 22, center }: {
  items: { label: string; value: number; color: string }[]; size?: number; thickness?: number;
  center?: { value: string; label: string };
}) {
  const total = items.reduce((a, b) => a + b.value, 0) || 1;
  const r = size / 2 - thickness / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#F1F1F1" strokeWidth={thickness} />
      {items.map((it, i) => {
        const len = (it.value / total) * c;
        const el = (
          <circle key={it.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={it.color} strokeWidth={thickness}
                  strokeDasharray={`${Math.max(0, len - 1.5)} ${c}`} strokeDashoffset={-offset}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`} className="donut-seg"
                  style={{ animationDelay: `${i * 90}ms` }}>
            <title>{`${it.label}: ${Math.round((100 * it.value) / total)}%`}</title>
          </circle>
        );
        offset += len;
        return el;
      })}
      {center && (
        <>
          <text x="50%" y="46%" textAnchor="middle" fontSize={size * 0.13} fontWeight={600} fill="#2C2C2C">{center.value}</text>
          <text x="50%" y="60%" textAnchor="middle" fontSize={11} fill="#6E6E6E">{center.label}</text>
        </>
      )}
    </svg>
  );
}

/** Stacked columns over time: ok and failed counts, with an optional line on top. */
export function Columns({ series, height = 180, labels }: {
  series: { ok: number; bad: number; line?: number; at: string }[]; height?: number; labels?: (at: string, i: number) => string | null;
}) {
  const max = Math.max(...series.map((s) => s.ok + s.bad), 1);
  const lmax = Math.max(...series.map((s) => s.line ?? 0), 1);
  const w = 100 / series.length;
  const line = series.map((s, i) => `${i ? "L" : "M"}${(i + 0.5) * w},${100 - ((s.line ?? 0) / lmax) * 92}`).join(" ");
  return (
    <div>
      <div className="relative" style={{ height }}>
        {[0.25, 0.5, 0.75].map((g) => (
          <div key={g} className="absolute inset-x-0 border-t border-dashed border-rule/70" style={{ bottom: `${g * 100}%` }} />
        ))}
        <div className="absolute inset-0 flex items-end gap-[3px]">
          {series.map((s, i) => {
            const total = s.ok + s.bad;
            return (
              <div key={i} className="group relative flex h-full flex-1 flex-col justify-end" title={`${s.ok + s.bad} calls${s.bad ? `, ${s.bad} failed` : ""}`}>
                <div className="col-grow flex flex-col justify-end overflow-hidden rounded-t-[3px]"
                     style={{ height: `${(total / max) * 100}%`, animationDelay: `${i * 22}ms` }}>
                  {s.bad > 0 && <div className="bg-rust" style={{ height: `${(s.bad / total) * 100}%` }} />}
                  <div className="flex-1 bg-signal/85 transition-colors group-hover:bg-signal" />
                </div>
              </div>
            );
          })}
        </div>
        {series.some((s) => s.line) && (
          <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d={line} fill="none" stroke="#F68511" strokeWidth={2} vectorEffect="non-scaling-stroke" className="chart-draw" pathLength={1} />
          </svg>
        )}
      </div>
      {labels && (
        <div className="mt-1.5 flex text-[10.5px] text-graphite">
          {series.map((s, i) => <span key={i} className="flex-1 text-center">{labels(s.at, i) ?? ""}</span>)}
        </div>
      )}
    </div>
  );
}
