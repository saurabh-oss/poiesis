import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Poiesis",
  description: "Autonomous engineering, with the human in the right loop",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <header className="console-header border-b border-rule">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-6 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              {/* Spectrum keeps the brand mark as the only saturated red on the page. */}
              <span
                aria-hidden
                className="brand-mark grid h-6 w-6 place-items-center rounded bg-brand text-[13px] font-bold leading-none text-paper"
              >
                P
              </span>
              <span className="text-[17px] font-semibold tracking-[-0.01em]">Poiesis</span>
            </Link>
            <span aria-hidden className="h-5 w-px bg-rule" />
            <p className="text-[13px] text-graphite">
              One brief in. A tested, reviewed increment out.
            </p>
            <nav className="ml-auto flex gap-1 text-[13px]">
              <Link href="/" className="nav-link rounded px-3 py-1.5 text-graphite hover:bg-mist hover:text-ink">
                Runs
              </Link>
              <Link href="/apps" className="nav-link rounded px-3 py-1.5 text-graphite hover:bg-mist hover:text-ink">
                Apps
              </Link>
              <Link href="/codebases" className="nav-link rounded px-3 py-1.5 text-graphite hover:bg-mist hover:text-ink">
                Codebases
              </Link>
              <Link href="/knowledge" className="nav-link rounded px-3 py-1.5 text-graphite hover:bg-mist hover:text-ink">
                Portfolio
              </Link>
              <Link href="/observability" className="nav-link rounded px-3 py-1.5 text-graphite hover:bg-mist hover:text-ink">
                Observability
              </Link>
            </nav>
          </div>
          <div aria-hidden className="console-hairline" />
        </header>
        <main className="mx-auto max-w-[1400px] px-6 py-8">{children}</main>
        {/* A soft light that follows the cursor across cards and panels. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let f = 0;
  document.addEventListener("pointermove", (e) => {
    if (f) return;
    f = requestAnimationFrame(() => {
      f = 0;
      const el = e.target.closest && e.target.closest('main section[class*="border"], main article[class*="border"], main a[class*="border"], main li[class*="border"]');
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", (e.clientX - r.left) + "px");
      el.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  }, { passive: true });
})();`,
          }}
        />
      </body>
    </html>
  );
}
