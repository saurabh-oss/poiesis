/**
 * The cast. Each agent has a colour of its own so that, across the rail, the
 * activity feed and the stage panels, you can tell who is speaking at a glance.
 * Colours come from Spectrum's categorical palette at a weight that holds white
 * initials; the semantic colours (positive, notice, negative) stay reserved for
 * status and are not reused as identities.
 */
export type AgentInfo = {
  key: string;
  name: string;
  role: string;
  initials: string;
  color: string;
};

export const AGENTS: Record<string, AgentInfo> = {
  intake: { key: "intake", name: "Intake", role: "Splits everything you gave it into cited fragments", initials: "In", color: "#0B78B8" },
  analyst: { key: "analyst", name: "Analyst", role: "Argues with the brief and asks what it leaves open", initials: "An", color: "#5258E4" },
  product_owner: { key: "product_owner", name: "Product Owner", role: "Writes the vision and the backlog, every claim cited", initials: "PO", color: "#8A3FD6" },
  architect: { key: "architect", name: "Architect", role: "Designs against what your portfolio already has", initials: "Ar", color: "#B130BD" },
  planner: { key: "planner", name: "Planner", role: "Cuts the slice that gets built now", initials: "Pl", color: "#0D8A80" },
  scaffold: { key: "scaffold", name: "Scaffold", role: "Lays down a working app before any feature code", initials: "Sc", color: "#4F7F12" },
  developer: { key: "developer", name: "Developer", role: "Implements each story inside the scaffold", initials: "De", color: "#0265DC" },
  tester: { key: "tester", name: "Tester", role: "Writes its own tests and assumes the code is wrong", initials: "Te", color: "#C8336E" },
  reviewer: { key: "reviewer", name: "Reviewer", role: "Scores the increment; the verdict is arithmetic", initials: "Re", color: "#1D6F8C" },
  release: { key: "release", name: "Release Manager", role: "Starts the app and writes notes you can read", initials: "RM", color: "#007A4D" },
  governance: { key: "governance", name: "Governance", role: "Holds the points where you decide", initials: "Go", color: "#9A6B12" },
  system: { key: "system", name: "Poiesis", role: "The platform itself", initials: "Po", color: "#6E6E6E" },
};

export function agent(key: string): AgentInfo {
  return (
    AGENTS[key] ?? {
      key,
      name: key.replace(/_/g, " "),
      role: "",
      initials: key.slice(0, 2),
      color: "#6E6E6E",
    }
  );
}

/** The eight agents a stakeholder meets, in the order they appear. */
export const CAST = [
  "analyst", "product_owner", "architect", "planner",
  "developer", "tester", "reviewer", "release",
];

/** Agents that narrate rather than work; they never count as "who is working". */
export const QUIET_AGENTS = new Set(["governance", "system"]);
