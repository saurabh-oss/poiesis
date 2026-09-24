"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Renders a Mermaid diagram in the Spectrum look, with pan, zoom and clickable nodes.
 *
 * Mermaid is loaded on first use (it is large) and initialised once. Clicks are
 * wired to the rendered DOM rather than through Mermaid's `click` directive, so the
 * diagram can stay in strict security mode: labels come from generated code.
 */

let loader: Promise<any> | null = null;
function mermaid(): Promise<any> {
  if (!loader) {
    loader = import("mermaid").then((m) => {
      const lib = m.default;
      lib.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        fontFamily: "'Source Sans 3', 'Adobe Clean', system-ui, sans-serif",
        flowchart: { curve: "basis", padding: 14, nodeSpacing: 34, rankSpacing: 56, htmlLabels: true },
        sequence: { mirrorActors: false, actorMargin: 60, messageFontSize: 13 },
        er: { layoutDirection: "LR", fontSize: 13 },
        themeVariables: {
          fontSize: "14px",
          primaryColor: "#F5F9FF",
          primaryBorderColor: "#0265DC",
          primaryTextColor: "#2C2C2C",
          secondaryColor: "#F8F8F8",
          tertiaryColor: "#FFFFFF",
          lineColor: "#8E8E8E",
          textColor: "#2C2C2C",
          clusterBkg: "#F8F8F8",
          clusterBorder: "#D5D5D5",
          edgeLabelBackground: "#FFFFFF",
          actorBkg: "#0265DC",
          actorBorder: "#0054B6",
          actorTextColor: "#FFFFFF",
          actorLineColor: "#B1B1B1",
          signalColor: "#4B4B4B",
          signalTextColor: "#2C2C2C",
          labelBoxBkgColor: "#FFF4E5",
          labelBoxBorderColor: "#DA7B11",
          noteBkgColor: "#FFF4E5",
          noteBorderColor: "#DA7B11",
          activationBkgColor: "#E9F2FD",
          activationBorderColor: "#0265DC",
          attributeBackgroundColorOdd: "#FFFFFF",
          attributeBackgroundColorEven: "#F8F8F8",
        },
      });
      return lib;
    });
  }
  return loader;
}

let seq = 0;

type Props = {
  code: string;
  /** Mermaid node id -> called when that node is clicked. */
  onNode?: (id: string) => void;
  selected?: string | null;
  /** Node ids to keep lit when something is selected; the rest dim. */
  lit?: Set<string> | null;
  interactive?: boolean;
  className?: string;
  minHeight?: number;
};

const NODE_ID = /flowchart-(.+)-\d+$/;

export default function Mermaid({ code, onNode, selected, lit, interactive = true, className = "", minHeight = 420 }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const view = useRef({ x: 0, y: 0, k: 1 });
  const natural = useRef({ w: 0, h: 0 });
  const onNodeRef = useRef(onNode);
  onNodeRef.current = onNode;

  const apply = useCallback(() => {
    const el = stage.current;
    if (!el) return;
    const { x, y, k } = view.current;
    el.style.transform = `translate(${x}px, ${y}px) scale(${k})`;
  }, []);

  const fit = useCallback(() => {
    const box = host.current;
    const { w, h } = natural.current;
    if (!box || !w || !h) return;
    const pad = 24;
    const k = Math.min((box.clientWidth - pad * 2) / w, (box.clientHeight - pad * 2) / h, 1.25);
    view.current = { k, x: (box.clientWidth - w * k) / 2, y: (box.clientHeight - h * k) / 2 };
    apply();
  }, [apply]);

  // Render.
  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setError(null);
    if (!code.trim()) return;
    (async () => {
      try {
        const lib = await mermaid();
        const { svg, bindFunctions } = await lib.render(`mmd-${++seq}`, code);
        if (cancelled || !stage.current) return;
        stage.current.innerHTML = svg;
        bindFunctions?.(stage.current);
        const el = stage.current.querySelector("svg") as SVGSVGElement | null;
        if (el) {
          const vb = el.viewBox.baseVal;
          natural.current = { w: vb?.width || el.getBBox().width, h: vb?.height || el.getBBox().height };
          el.setAttribute("width", String(natural.current.w));
          el.setAttribute("height", String(natural.current.h));
          el.style.maxWidth = "none";
          el.querySelectorAll<SVGGElement>("g.node").forEach((g, i) => {
            g.style.animationDelay = `${Math.min(i * 28, 700)}ms`;
            const m = NODE_ID.exec(g.id);
            if (m && onNodeRef.current) {
              g.dataset.node = m[1];
              g.classList.add("mmd-clickable");
            }
          });
        }
        setReady(true);
        requestAnimationFrame(fit);
      } catch (e: any) {
        if (!cancelled) setError(String(e?.message ?? e).split("\n")[0].slice(0, 240));
      }
    })();
    return () => { cancelled = true; };
  }, [code, fit]);

  // Selection and neighbourhood highlight.
  useEffect(() => {
    const el = stage.current;
    if (!el || !ready) return;
    el.querySelectorAll<SVGGElement>("g.node").forEach((g) => {
      const id = g.dataset.node;
      g.classList.toggle("mmd-selected", !!selected && id === selected);
      g.classList.toggle("mmd-dim", !!lit && !!id && !lit.has(id));
    });
    // Edge ids are `L_<source>_<target>_<n>`.
    const tail = selected ? new RegExp(`_${selected}_\\d+$`) : null;
    el.querySelectorAll<SVGPathElement>("path.flowchart-link, .edgePaths path").forEach((p) => {
      const on = !!selected && (p.id.startsWith(`L_${selected}_`) || !!tail?.test(p.id));
      p.classList.toggle("mmd-edge-on", on);
      p.classList.toggle("mmd-dim", !!lit && !!selected && !on);
    });
  }, [selected, lit, ready]);

  // Pan (drag), zoom (wheel), click.
  useEffect(() => {
    const box = host.current;
    if (!box || !interactive) return;
    let drag: { x: number; y: number; vx: number; vy: number; moved: boolean } | null = null;
    const down = (e: PointerEvent) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, vx: view.current.x, vy: view.current.y, moved: false };
    };
    const move = (e: PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      if (!drag.moved) box.setPointerCapture(e.pointerId);
      drag.moved = true;
      box.classList.add("mmd-grabbing");
      view.current.x = drag.vx + dx;
      view.current.y = drag.vy + dy;
      apply();
    };
    const up = (e: PointerEvent) => {
      const wasDrag = drag?.moved;
      drag = null;
      box.classList.remove("mmd-grabbing");
      if (wasDrag) return;
      const g = (e.target as Element | null)?.closest?.("g.node") as SVGGElement | null;
      if (g?.dataset.node) onNodeRef.current?.(g.dataset.node);
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = box.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const v = view.current;
      const k = Math.min(4, Math.max(0.15, v.k * Math.exp(-e.deltaY * 0.0015)));
      v.x = px - ((px - v.x) * k) / v.k;
      v.y = py - ((py - v.y) * k) / v.k;
      v.k = k;
      apply();
    };
    box.addEventListener("pointerdown", down);
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up);
    box.addEventListener("wheel", wheel, { passive: false });
    const ro = new ResizeObserver(() => fit());
    ro.observe(box);
    return () => {
      box.removeEventListener("pointerdown", down);
      box.removeEventListener("pointermove", move);
      box.removeEventListener("pointerup", up);
      box.removeEventListener("wheel", wheel);
      ro.disconnect();
    };
  }, [interactive, apply, fit]);

  const zoom = (f: number) => {
    const box = host.current;
    if (!box) return;
    const v = view.current;
    const px = box.clientWidth / 2, py = box.clientHeight / 2;
    const k = Math.min(4, Math.max(0.15, v.k * f));
    v.x = px - ((px - v.x) * k) / v.k;
    v.y = py - ((py - v.y) * k) / v.k;
    v.k = k;
    apply();
  };

  return (
    <div className={`mmd relative overflow-hidden ${className}`} style={{ minHeight }}>
      <div ref={host} className={`absolute inset-0 ${interactive ? "cursor-grab" : ""}`}>
        <div ref={stage} className={`mmd-stage origin-top-left ${ready ? "mmd-ready" : ""}`} />
      </div>
      {!ready && !error && code.trim() && (
        <div className="absolute inset-0 grid place-items-center">
          <div className="skeleton h-2/3 w-2/3 rounded-lg" />
        </div>
      )}
      {error && (
        <p className="absolute inset-x-4 top-4 rounded border border-rust/40 bg-paper px-3 py-2 text-[12px] text-rust">
          This diagram could not be drawn: {error}
        </p>
      )}
      {interactive && ready && (
        <div className="absolute bottom-3 right-3 flex overflow-hidden rounded-full border border-rule bg-paper/90 text-[13px] shadow-spectrum backdrop-blur">
          <button onClick={() => zoom(1 / 1.25)} className="px-3 py-1 hover:bg-mist" aria-label="Zoom out">−</button>
          <button onClick={fit} className="border-x border-rule px-3 py-1 hover:bg-mist">Fit</button>
          <button onClick={() => zoom(1.25)} className="px-3 py-1 hover:bg-mist" aria-label="Zoom in">+</button>
        </div>
      )}
    </div>
  );
}
