import type { ReactNode } from "react";

/** A small monoline icon set: one per stage, plus the handful of UI glyphs. */
const PATHS: Record<string, ReactNode> = {
  intake: <><path d="M3 13h5l1.5 3h5L16 13h5" /><path d="M5 5h14l2 8v6H3v-6z" /></>,
  discovery: <><circle cx="11" cy="11" r="6.5" /><path d="M20.5 20.5 16 16" /><path d="M9.6 9.3a1.6 1.6 0 1 1 2.2 1.5c-.5.2-.8.6-.8 1.1v.4" /></>,
  vision: <><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="2.8" /></>,
  backlog: <><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>,
  architecture: <><path d="m12 3 9 5-9 5-9-5 9-5z" /><path d="m3 13 9 5 9-5" /></>,
  sprint: <><path d="M5 21V4" /><path d="M5 4h11l-2.2 4L16 12H5" /></>,
  scaffold: <><rect x="3.5" y="3.5" width="17" height="17" rx="1.5" /><path d="M3.5 9.5h17M9.5 9.5v11" /></>,
  build: <><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></>,
  review: <><circle cx="12" cy="12" r="9" /><path d="m8.5 12.2 2.3 2.3 4.7-4.8" /></>,
  deploy: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18" /></>,
  release: <><path d="m3 7.5 9-4.5 9 4.5v9L12 21l-9-4.5z" /><path d="m3 7.5 9 4.5 9-4.5M12 12v9" /></>,
  harvest: <><circle cx="6" cy="6.5" r="2.3" /><circle cx="18" cy="8" r="2.3" /><circle cx="9.5" cy="18" r="2.3" /><path d="m8.2 7.1 7.5 1.1M7.1 8.6l1.6 7.3M16.4 9.8l-5 6.6" /></>,
  check: <path d="m5 12.5 4.2 4.2L19 7" />,
  x: <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />,
  alert: <><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5M12 16.4v.1" /></>,
  pause: <path d="M9 6v12M15 6v12" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
  image: <><rect x="3.5" y="4.5" width="17" height="15" rx="1.5" /><circle cx="9" cy="10" r="1.8" /><path d="m4 18 5.5-5 4 3.5 2.5-2 4 3.5" /></>,
  audio: <><path d="M9 18V6l10-2v12" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="16.5" cy="16" r="2.5" /></>,
  link: <><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>,
  upload: <><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v4h16v-4" /></>,
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.6 2.6M15.4 15.4 18 18M6 18l2.6-2.6M15.4 8.6 18 6" />,
  external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v6H4V6h6" /></>,
  flask: <><path d="M9 3h6M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" /><path d="M7.5 15h9" /></>,
  map: <><path d="m3 6 6-2.5 6 2.5 6-2.5v15L15 21l-6-2.5L3 21z" /><path d="M9 3.5v15M15 6v15" /></>,
  wrench: <path d="M14.5 5.5a4 4 0 0 0 5 5L12 18a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-2-2z" />,
  users: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20c.6-3.4 3-5.3 6-5.3s5.4 1.9 6 5.3" /><path d="M16 5a3 3 0 0 1 0 6M18 14.8c1.8.7 2.8 2.4 3 5.2" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  down: <path d="M12 5v14M6 13l6 6 6-6" />,
  dot: <circle cx="12" cy="12" r="3" />,
};

export default function Icon({
  name, size = 16, className = "", strokeWidth = 1.8,
}: { name: string; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden
    >
      {PATHS[name] ?? PATHS.dot}
    </svg>
  );
}
