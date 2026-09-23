"""The value stream, as an explicit graph.

Keeping the stream declarative here — rather than as agents calling agents — is what
makes it auditable. You can read this file and know exactly what the platform will do,
which gates exist, and where it can loop.
"""
from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from ..config import pack, settings
from .nodes.build import build
from .nodes.deploy import deploy_increment
from .nodes.design import architecture, plan_sprint
from .nodes.discovery import analyse, intake
from .nodes.foundation import lay_foundation
from .nodes.product import backlog, vision
from .nodes.scaffold import bootstrap
from .nodes.ship import harvest, release, review
from .state import RunState

def _max_rework_rounds() -> int:
    return int(pack().get("build", {}).get("max_rework_rounds", 2))


def _after_review(state: RunState) -> str:
    """A rework verdict sends the faulted stories back through build, a bounded
    number of times, then escalates to the stakeholder at the release gate."""
    verdict = state.get("review", {}).get("computed_verdict")
    attempts = state.get("repair_attempts", 0)
    if verdict == "rework" and attempts < _max_rework_rounds():
        return "rebuild"
    return "release"


def _after_release(state: RunState) -> str:
    """The stakeholder can send an unreleasable increment back for another round."""
    return "rebuild" if (state.get("release") or {}).get("status") == "rebuild" else "harvest"


async def _mark_rework(state: RunState) -> RunState:
    return {"repair_attempts": state.get("repair_attempts", 0) + 1}


def build_graph() -> StateGraph:
    """Node names are deliberately verbs: LangGraph reserves state keys, and the state
    already holds nouns like `vision` and `review`. Stage keys shown in the UI are
    separate strings set via set_stage()."""
    g = StateGraph(RunState)

    g.add_node("capture", intake)
    g.add_node("interrogate", analyse)
    g.add_node("write_vision", vision)
    g.add_node("write_backlog", backlog)
    g.add_node("design", architecture)
    g.add_node("plan", plan_sprint)
    g.add_node("bootstrap", bootstrap)
    g.add_node("found", lay_foundation)
    g.add_node("implement", build)
    g.add_node("assess", review)
    g.add_node("rework", _mark_rework)
    g.add_node("deploy", deploy_increment)
    g.add_node("ship", release)
    g.add_node("harvest", harvest)

    g.add_edge(START, "capture")
    g.add_edge("capture", "interrogate")
    g.add_edge("interrogate", "write_vision")
    g.add_edge("write_vision", "write_backlog")
    g.add_edge("write_backlog", "design")
    g.add_edge("design", "plan")
    g.add_edge("plan", "bootstrap")
    # The data model and the demonstration data are laid once, for every story,
    # so each story builds a screen over tables that exist and hold real-looking
    # rows. A rework round goes straight back to build.
    g.add_edge("bootstrap", "found")
    g.add_edge("found", "implement")
    # Deploy before review: every round is started and opened in a real browser,
    # and the review judges what actually works rather than what the code claims.
    g.add_edge("implement", "deploy")
    g.add_edge("deploy", "assess")
    g.add_conditional_edges("assess", _after_review,
                            {"rebuild": "rework", "release": "ship"})
    g.add_edge("rework", "implement")
    g.add_conditional_edges("ship", _after_release,
                            {"rebuild": "rework", "harvest": "harvest"})
    g.add_edge("harvest", END)
    return g


STAGES = [
    ("intake", "Intake", "Everything the stakeholder gave us, split into cited fragments"),
    ("discovery", "Discovery", "The Analyst interrogates the brief and asks what is missing"),
    ("vision", "Vision", "Product Vision, every claim traced to evidence"),
    ("backlog", "Backlog", "Epics and stories with testable acceptance criteria"),
    ("architecture", "Architecture", "Design constrained by what the portfolio already has"),
    ("sprint", "Sprint", "The slice that gets built now"),
    ("scaffold", "Scaffold", "A running application skeleton, before any feature code"),
    ("foundation", "Foundation", "The whole data model and believable demonstration data, before any story"),
    ("build", "Build", "Developer implements, Tester verifies, repair loop closes the gap"),
    ("deploy", "Deploy", "The increment running at a URL, every screen opened in a real browser"),
    ("review", "Review", "Independent weighted verdict on the code and on what actually runs"),
    ("release", "Release", "Packaged increment and a note the stakeholder can read"),
    ("harvest", "Harvest", "What we learned goes back into the knowledge graph"),
]

# What each stage does, who does it, and whether it can stop to ask. The UI shows
# this before a stage runs, so a stakeholder sees what is coming rather than
# "not started". `gate` names the pack gate that can pause the stage; the pack
# decides whether it actually stops (mode: require) or records and moves on.
STAGE_DETAIL: dict[str, dict] = {
    "intake": {"agents": ["intake"], "gate": None, "asks": "",
               "produces": "Cited evidence fragments from everything you provided"},
    "discovery": {"agents": ["analyst"], "gate": "clarify",
                  "produces": "The Analyst's understanding of the brief, any contradictions, and up to six questions with proposed answers",
                  "asks": "Answer the questions the brief left open, or accept the Analyst's proposed defaults."},
    "vision": {"agents": ["product_owner"], "gate": "approve_vision",
               "produces": "A product vision: the problem, who it is for, how success is measured, and what is out of scope",
               "asks": "Confirm the vision describes the product you asked for, or send it back with changes."},
    "backlog": {"agents": ["product_owner"], "gate": "approve_backlog",
                "produces": "Epics and user stories, each with acceptance criteria that can be tested",
                "asks": "Approve the stories, or reprioritise before the sprint is cut."},
    "architecture": {"agents": ["architect"], "gate": "approve_architecture",
                     "produces": "A design with a reuse verdict for every capability, checked against your portfolio",
                     "asks": "Accept the design and its reuse decisions, or push back on anything built new."},
    "sprint": {"agents": ["planner"], "gate": "approve_sprint",
               "produces": "The sprint goal and the stories that will be built now",
               "asks": "Confirm the scope of the first increment."},
    "scaffold": {"agents": ["scaffold"], "gate": None, "asks": "",
                 "produces": "A working frontend, API and database, laid down before any feature code"},
    "foundation": {"agents": ["developer", "data_designer"], "gate": None, "asks": "",
                   "produces": "Every table the stories need, and a generated demonstration data set the app opens with"},
    "build": {"agents": ["developer", "tester"], "gate": "failed_story",
              "produces": "Code, tests and a screen for each story, repaired until the tests and the platform's frontend checks pass",
              "asks": "Stops only if a story still fails after its repairs: carry on, drop it, or stop the sprint."},
    "deploy": {"agents": ["release"], "gate": None, "asks": "",
               "produces": "The application running at an address you can open, with every screen checked in a real browser and screenshotted"},
    "review": {"agents": ["reviewer"], "gate": None, "asks": "",
               "produces": "A weighted score across five dimensions and a computed verdict; a screen that failed in the browser sends its story back"},
    "release": {"agents": ["release"], "gate": "approve_release",
                "produces": "A version and release notes written for you",
                "asks": "Try the running app, then release it, send it back for another round, or hold it. An app that is not proven working, or that the Reviewer blocks, cannot be released."},
    "harvest": {"agents": ["governance"], "gate": None, "asks": "",
                "produces": "What this run learned, added to the knowledge graph for the next one"},
}


async def compiled_graph():
    """Compile with a Postgres checkpointer so interrupts survive restarts."""
    saver_cm = AsyncPostgresSaver.from_conn_string(settings().checkpoint_dsn)
    saver = await saver_cm.__aenter__()
    await saver.setup()
    return build_graph().compile(checkpointer=saver), saver_cm
