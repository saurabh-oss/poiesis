import type { Config } from "tailwindcss";

/**
 * Adobe Spectrum palette.
 *
 * The token names are unchanged so every component keeps working; only the values
 * move. Greys are Spectrum's neutral ramp, the accent is Spectrum blue, and the
 * semantic three (positive / notice / negative) are Spectrum's, not invented —
 * which is what keeps a status colour meaning the same thing in every view.
 */
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FFFFFF",      // gray-50   page ground
        mist: "#F8F8F8",       // gray-100  subdued surface
        rule: "#E1E1E1",       // gray-300  hairlines and field borders
        ink: "#2C2C2C",        // gray-800  primary text
        graphite: "#6E6E6E",   // gray-600  secondary text
        signal: "#0265DC",     // blue-800  accent, selection, in-progress
        ochre: "#DA7B11",      // orange-800 notice — an open gate
        moss: "#007A4D",       // green-800 positive — a stage that passed
        rust: "#D31510",       // red-800   negative — a failure
        brand: "#EB1000",      // Adobe red, reserved for the wordmark
        slate: "#4B4B4B",      // gray-700  headings on subdued surfaces
      },
      fontFamily: {
        // Adobe Clean is proprietary; Source Sans and Source Code are Adobe's own
        // open faces and the closest honest match.
        sans: ["'Source Sans 3'", "'Adobe Clean'", "system-ui", "sans-serif"],
        mono: ["'Source Code Pro'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        // Spectrum's regular corner radius.
        DEFAULT: "4px",
        spectrum: "4px",
      },
      boxShadow: {
        spectrum: "0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)",
      },
    },
  },
  plugins: [],
} satisfies Config;
