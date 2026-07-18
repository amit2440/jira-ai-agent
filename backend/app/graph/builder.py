"""LangGraph topology for the AI Requirements Assistant — 5-flow architecture.

Five agent flows
────────────────
  rag_qa     — BRD / knowledge Q&A            (immediate, no approval)
  jira_qa    — Live Jira data Q&A via NL→JQL  (immediate, no approval)
  hybrid_qa  — BRD + Jira gap analysis        (immediate, no approval)
  ticket     — Draft → human approval → Jira  (human-in-the-loop)
  report     — Plan → write → review → approval → export  (human-in-the-loop)

Topology vs. execution engine
──────────────────────────────
This graph defines the authoritative node topology and is compiled so that
GET /api/graph can render an accurate Mermaid diagram.  The active execution
engine is workflow.py, which calls agent/tool functions directly and mirrors
every node and edge defined here.  To promote this graph to the primary
runtime, replace the stub node functions below with real calls into the
agents/ and tools/ modules and add a MemorySaver checkpointer.

Decision points
───────────────
  pii_validation  → "router" (safe) | END (PII detected)
  router          → one of five flow entry nodes based on state["flow"]
  human_approval  → "jira_tool" (ticket approved) |
                    "report_export" (report approved) |
                    "logging" (rejected — skips action, goes to finalize)
"""
from typing import Literal

from langgraph.graph import END, START, StateGraph

from .state import GraphState


# ── Node implementations (topology-correct stubs; execution lives in workflow.py) ──

def _pii_validation(state: GraphState) -> dict:
    """Gate: block runs that contain PII before any LLM call."""
    return {}  # workflow.py sets status="failed" on PII hit


def _project_validation(state: GraphState) -> dict:
    """Gate: verify project key exists in BRD corpus and/or live Jira before routing."""
    return {}  # workflow.py sets status="failed" if neither source recognises the key


def _router(state: GraphState) -> dict:
    """Classify the user request into one of five flows via LLM + heuristic fallback."""
    return {}  # flow and router_decision populated by workflow.route_request()


# ── Q&A flow nodes ──────────────────────────────────────────────────────────────

def _rag_retrieval(state: GraphState) -> dict:
    """Retrieve top-k documents from the SQLite knowledge base using hybrid (BM25 + vector) search."""
    return {}


def _rag_qa_agent(state: GraphState) -> dict:
    """Answer the question grounded in the retrieved BRD documents; return confidence."""
    return {"status": "completed"}


def _nl_to_jql(state: GraphState) -> dict:
    """Translate the natural-language question into a scoped Jira JQL query."""
    return {}  # populates jql_query


def _jira_search(state: GraphState) -> dict:
    """Execute the JQL query against the Jira REST API and return matching issues."""
    return {}


def _jira_qa_agent(state: GraphState) -> dict:
    """Synthesise a factual answer from the retrieved Jira issue data."""
    return {"status": "completed"}


def _hybrid_retrieval(state: GraphState) -> dict:
    """Retrieve BRD documents (hybrid search) AND Jira project health metrics in parallel."""
    return {}


def _hybrid_qa_agent(state: GraphState) -> dict:
    """Cross-reference BRD requirements vs Jira coverage; identify gaps."""
    return {"status": "completed"}


# ── Ticket flow nodes ────────────────────────────────────────────────────────────

def _requirement_enhancement(state: GraphState) -> dict:
    """Normalise the requirement text and redact any residual PII."""
    return {}  # populates enhanced_text


def _ticket_retrieval(state: GraphState) -> dict:
    """Retrieve relevant BRD context to ground the ticket draft."""
    return {}


def _ticket_generation(state: GraphState) -> dict:
    """Generate a structured Jira ticket draft (summary, description, AC, priority)."""
    return {"status": "awaiting_approval"}


# ── Report flow nodes ────────────────────────────────────────────────────────────

def _jira_health(state: GraphState) -> dict:
    """Fetch aggregated Jira metrics: open defects, blockers, completed items, health."""
    return {}


def _planner(state: GraphState) -> dict:
    """Plan the report structure (sections, title) from the Jira metrics context."""
    return {}


def _writer(state: GraphState) -> dict:
    """Write the full Markdown report body following the planner's outline."""
    return {}


def _reviewer(state: GraphState) -> dict:
    """Quality-review the draft; return revised Markdown and review notes."""
    return {"status": "awaiting_approval"}


# ── Shared action / post-processing nodes ────────────────────────────────────────

def _human_approval(state: GraphState) -> dict:
    """Interrupt point — execution pauses until the user approves or rejects the draft."""
    return {}


def _jira_tool(state: GraphState) -> dict:
    """Create the approved ticket in Jira via REST API (ADF description format)."""
    return {"status": "completed"}


def _report_export(state: GraphState) -> dict:
    """Write the approved report to backend/exports/<run_id>-<title>.md."""
    return {"status": "completed"}


def _logging(state: GraphState) -> dict:
    """Persist the final execution trace and close the run."""
    return {"status": "completed"}


# ── Conditional edge functions ────────────────────────────────────────────────────

def _after_pii(
    state: GraphState,
) -> Literal["project_validation", "__end__"]:
    """Abort early if PII was detected; otherwise proceed to project validation."""
    return "__end__" if state.get("status") == "failed" else "project_validation"


def _after_project_validation(
    state: GraphState,
) -> Literal["router", "__end__"]:
    """Abort if project key not recognised in BRD or Jira; otherwise route."""
    return "__end__" if state.get("status") == "failed" else "router"


def _after_router(
    state: GraphState,
) -> Literal[
    "rag_retrieval",
    "nl_to_jql",
    "hybrid_retrieval",
    "requirement_enhancement",
    "jira_health",
]:
    """Dispatch to the entry node for the classified flow."""
    return {
        "rag_qa":    "rag_retrieval",
        "jira_qa":   "nl_to_jql",
        "hybrid_qa": "hybrid_retrieval",
        "ticket":    "requirement_enhancement",
        "report":    "jira_health",
    }.get(state.get("flow") or "rag_qa", "rag_retrieval")


def _after_approval(
    state: GraphState,
) -> Literal["jira_tool", "report_export", "logging"]:
    """Route post-approval: create Jira issue, export report, or skip on rejection."""
    if not state.get("approved"):
        return "logging"
    return "jira_tool" if state.get("flow") == "ticket" else "report_export"


# ── Graph assembly ────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(GraphState)

    # ── Register all nodes ───────────────────────────────────────────────────────
    graph.add_node("pii_validation",          _pii_validation)
    graph.add_node("project_validation",      _project_validation)
    graph.add_node("router",                  _router)

    # Q&A flows
    graph.add_node("rag_retrieval",           _rag_retrieval)
    graph.add_node("rag_qa_agent",            _rag_qa_agent)
    graph.add_node("nl_to_jql",               _nl_to_jql)
    graph.add_node("jira_search",             _jira_search)
    graph.add_node("jira_qa_agent",           _jira_qa_agent)
    graph.add_node("hybrid_retrieval",        _hybrid_retrieval)
    graph.add_node("hybrid_qa_agent",         _hybrid_qa_agent)

    # Ticket flow
    graph.add_node("requirement_enhancement", _requirement_enhancement)
    graph.add_node("ticket_retrieval",        _ticket_retrieval)
    graph.add_node("ticket_generation",       _ticket_generation)

    # Report flow
    graph.add_node("jira_health",             _jira_health)
    graph.add_node("planner",                 _planner)
    graph.add_node("writer",                  _writer)
    graph.add_node("reviewer",                _reviewer)

    # Shared
    graph.add_node("human_approval",          _human_approval)
    graph.add_node("jira_tool",               _jira_tool)
    graph.add_node("report_export",           _report_export)
    graph.add_node("logging",                 _logging)

    # ── Edges ────────────────────────────────────────────────────────────────────
    graph.add_edge(START, "pii_validation")

    graph.add_conditional_edges("pii_validation", _after_pii, {
        "project_validation": "project_validation",
        "__end__":            END,
    })

    graph.add_conditional_edges("project_validation", _after_project_validation, {
        "router":  "router",
        "__end__": END,
    })

    # Router → one of five flow entry nodes
    graph.add_conditional_edges("router", _after_router)

    # ── RAG Q&A ──
    graph.add_edge("rag_retrieval",    "rag_qa_agent")
    graph.add_edge("rag_qa_agent",     "logging")

    # ── Jira Q&A ──
    graph.add_edge("nl_to_jql",        "jira_search")
    graph.add_edge("jira_search",      "jira_qa_agent")
    graph.add_edge("jira_qa_agent",    "logging")

    # ── Hybrid Q&A ──
    graph.add_edge("hybrid_retrieval", "hybrid_qa_agent")
    graph.add_edge("hybrid_qa_agent",  "logging")

    # ── Ticket flow ──
    graph.add_edge("requirement_enhancement", "ticket_retrieval")
    graph.add_edge("ticket_retrieval",        "ticket_generation")
    graph.add_edge("ticket_generation",       "human_approval")

    # ── Report flow ──
    graph.add_edge("jira_health", "planner")
    graph.add_edge("planner",     "writer")
    graph.add_edge("writer",      "reviewer")
    graph.add_edge("reviewer",    "human_approval")

    # ── Approval gate (shared by ticket + report) ──
    graph.add_conditional_edges("human_approval", _after_approval)

    graph.add_edge("jira_tool",     "logging")
    graph.add_edge("report_export", "logging")
    graph.add_edge("logging",       END)

    return graph.compile()
