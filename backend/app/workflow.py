"""
Entry-point glue for the 5-flow agent graph — supports:

  rag_qa     — immediate BRD Q&A (no approval)
  jira_qa    — immediate Jira Q&A (no approval, uses NL→JQL)
  hybrid_qa  — immediate BRD + Jira gap analysis (no approval)
  ticket     — generate draft → human approval → create in Jira
  report     — generate draft → human approval → export

Entry points:
  chat(req, graph)                      — unified chat interface (auto-routes)
  chat_stream(req, graph)                — same, yields step events as nodes complete
  start(req, graph)                     — legacy /api/runs entry point (backward compat)
  approve(run_id, approved, feedback, graph) — human approval for ticket/report flows
  get_run_state(run_id, graph)          — legacy /api/runs/{run_id} read

`graph` is the compiled `StateGraph` from `graph.builder.build_graph()` (built
once at FastAPI startup, checkpointed with SqliteSaver). All pipeline logic —
PII/project validation, routing, retrieval, synthesis, ticket/report
generation, human-in-the-loop approval — lives in the graph's nodes
(`graph/builder.py`). This module only builds the initial `GraphState`,
invokes/resumes the graph, and shapes the result into the HTTP response
models the frontend already expects.
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from langgraph.types import Command

from .agents.report import ReportLLMUnavailable
from .agents.ticket import TicketLLMUnavailable
from .config import JIRA_PROJECT_KEY
from .graph.bridge import to_run_state
from .memory import append_turn, get_history
from .models import ChatRequest, ChatResponse, PendingAction, RunRequest, RunState, SourceRef

_AFFIRMATIVES = {
    "yes", "yep", "yeah", "sure", "ok", "okay", "go", "do it",
    "generate", "generate them", "create them", "proceed", "continue", "please",
    "next", "next one", "more",
}

# Node name → user-facing progress label, for chat_stream()'s step events.
NODE_LABELS = {
    "pii_validation":          "Checking your message…",
    "project_validation":      "Validating project…",
    "router":                  "Classifying your request…",
    "react_retrieval":         "Searching BRD + Jira…",
    "rag_qa_agent":            "Generating answer…",
    "jira_qa_agent":           "Generating answer…",
    "hybrid_qa_agent":         "Cross-referencing BRD + Jira…",
    "requirement_enhancement": "Enhancing requirement…",
    "ticket_retrieval":        "Searching BRD…",
    "contradiction_check":     "Checking for contradictions…",
    "ticket_generation":       "Drafting ticket…",
    "jira_health":             "Fetching Jira metrics…",
    "planner":                 "Planning report…",
    "writer":                  "Writing report…",
    "reviewer":                "Reviewing report…",
    "reflection_check":        "Checking report quality…",
    "confidence_check":        "Finalizing confidence check…",
    "human_approval":          "Awaiting your approval…",
    "jira_tool":               "Creating Jira ticket…",
    "report_export":           "Exporting report…",
    "logging":                 "Wrapping up…",
}


def _make_source_refs(docs: list[dict[str, Any]], source: str = "knowledge") -> list[SourceRef]:
    return [
        SourceRef(
            title=d.get("title", "Document"),
            content=d.get("content", ""),
            score=d.get("score"),
            bm25_score=d.get("bm25_score"),
            vector_score=d.get("vector_score"),
            rerank_score=d.get("rerank_score"),
            source=source,
        )
        for d in docs
    ]


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _llm_unavailable_response(run_id: str, exc: Exception) -> ChatResponse:
    flow = "ticket" if isinstance(exc, TicketLLMUnavailable) else "report"
    return ChatResponse(
        run_id=run_id, thread_id=run_id, flow=flow, status="failed",
        error=f"LLM unavailable — {flow} generation requires a working LLM connection. Details: {exc}",
    )


def _build_chat_state(req: ChatRequest) -> tuple[str, str, dict]:
    """Shared pre-processing for chat()/chat_stream(): gap-cycling rewrite,
    conversation history load, initial GraphState. Returns (run_id, session_id, state)."""
    session_id = req.session_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    project_key = (req.project_key or JIRA_PROJECT_KEY or "EOMS").upper()
    text = req.text

    pending_gaps: list[str] = []
    pending_topic = ""
    if req.pending_action and req.pending_action.type == "generate_tickets":
        normalized = text.strip().lower().rstrip("!.,")
        if normalized in _AFFIRMATIVES or len(text.strip()) <= 20:
            pa = req.pending_action
            if pa.gaps:
                first_gap = pa.gaps[0]
                pending_gaps = pa.gaps[1:]
                pending_topic = pa.topic
                topic_prefix = f"{pa.topic} " if pa.topic else ""
                text = (
                    f"Create a user story for: {first_gap}. "
                    f"This is a missing {topic_prefix}requirement in the EOMS project."
                )

    history = get_history(session_id)
    append_turn(session_id, "user", text, flow=None)

    initial_state = {
        "thread_id": run_id,
        "run_id": run_id,
        "text": text,
        "flow": None,
        "project_key": project_key,
        "session_id": session_id,
        "llm_params": req.llm_params.model_dump() if req.llm_params else None,
        "conversation_history": history,
        "pending_gaps": pending_gaps,
        "pending_topic": pending_topic,
    }
    return run_id, session_id, initial_state


def _build_chat_response(run_id: str, final_state: dict) -> ChatResponse:
    """Shared post-processing for chat()/chat_stream(): shape final GraphState into ChatResponse."""
    run = to_run_state(final_state)

    if run.status == "failed":
        return ChatResponse(
            run_id=run_id, thread_id=run_id, flow=run.flow or "rag_qa",
            status="failed", error=run.error,
        )

    if run.status == "awaiting_approval":
        source_type = "knowledge" if run.flow == "ticket" else "jira"
        next_pending = None
        if run.pending_gaps:
            n = len(run.pending_gaps)
            next_pending = PendingAction(
                type="generate_tickets",
                description=f"Generate Jira stories for {n} more missing requirement{'s' if n != 1 else ''}",
                gaps=run.pending_gaps,
                topic=run.pending_topic,
            )
        return ChatResponse(
            run_id=run_id, thread_id=run_id, flow=run.flow, status=run.status,
            draft=run.result,
            sources=_make_source_refs(run.retrieved_documents, source_type),
            events=run.events,
            model=run.model, total_tokens=run.total_tokens,
            error=run.error,
            pending_action=next_pending,
        )

    # ── Completed Q&A flow ──────────────────────────────────────────────
    payload = run.result.get("answer", {})
    if run.session_id:
        answer_text = payload.get("answer", "")
        if isinstance(answer_text, str):
            append_turn(run.session_id, "assistant", answer_text[:1000], flow=run.flow)

    if run.flow == "jira_qa":
        source_type, all_docs = "jira", final_state.get("jira_docs") or []
    elif run.flow == "hybrid_qa":
        source_type = "knowledge"
        all_docs = (final_state.get("brd_docs") or []) + (final_state.get("jira_docs") or [])
    else:  # rag_qa
        source_type, all_docs = "knowledge", final_state.get("brd_docs") or []

    pending = None
    if run.flow == "hybrid_qa":
        gaps = payload.get("gaps", [])
        if gaps:
            import re as _re
            _topic_patterns = {
                "security": r"\b(security|auth|authentication|authorization|rbac|jwt|permission)\b",
                "performance": r"\b(performance|sla|latency|throughput|scalability)\b",
                "integration": r"\b(integrat|api|external|third.party|connect)\b",
                "document": r"\b(document|upload|attach|file|storage)\b",
            }
            topic = ""
            for _cat, _pat in _topic_patterns.items():
                if _re.search(_pat, run.text, _re.I):
                    topic = _cat
                    break
            pending = PendingAction(
                type="generate_tickets",
                description=f"Generate Jira stories for {len(gaps)} missing requirements",
                gaps=gaps,
                topic=topic,
            )

    return ChatResponse(
        run_id=run_id, thread_id=run_id, flow=run.flow, status="completed",
        answer=payload,
        sources=_make_source_refs(all_docs, source_type),
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
        pending_action=pending,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED CHAT ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def chat(req: ChatRequest, graph) -> ChatResponse:
    """
    Unified entry point for the chat interface.
    Routes to the correct flow and returns either an immediate answer (Q&A flows)
    or a draft awaiting approval (ticket/report flows).
    """
    run_id, _session_id, initial_state = _build_chat_state(req)
    try:
        final_state = await graph.ainvoke(initial_state, _config(run_id))
    except (ReportLLMUnavailable, TicketLLMUnavailable) as exc:
        return _llm_unavailable_response(run_id, exc)
    return _build_chat_response(run_id, final_state)


async def chat_stream(req: ChatRequest, graph) -> AsyncIterator[dict]:
    """
    Same as chat(), but yields progress events as each graph node completes:
      {"type": "step", "node": "react_retrieval", "message": "Searching BRD + Jira…"}
      ...
      {"type": "done", "response": <ChatResponse dict>}
    or on failure:
      {"type": "done", "response": <ChatResponse dict with status="failed">}
    """
    run_id, _session_id, initial_state = _build_chat_state(req)
    config = _config(run_id)
    try:
        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
            for node in chunk:
                if node == "__interrupt__":
                    continue
                yield {"type": "step", "node": node, "message": NODE_LABELS.get(node, node)}
    except (ReportLLMUnavailable, TicketLLMUnavailable) as exc:
        response = _llm_unavailable_response(run_id, exc)
        yield {"type": "done", "response": response.model_dump(mode="json")}
        return

    snapshot = await graph.aget_state(config)
    response = _build_chat_response(run_id, snapshot.values)
    yield {"type": "done", "response": response.model_dump(mode="json")}


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL
# ═══════════════════════════════════════════════════════════════════════════════

async def approve(run_id: str, approved: bool, feedback: str | None, graph) -> RunState:
    final_state = await graph.ainvoke(Command(resume={"approved": approved, "feedback": feedback}), _config(run_id))
    return to_run_state(final_state)


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY /api/runs ENTRY POINTS (backward compat)
# ═══════════════════════════════════════════════════════════════════════════════

async def start(req: RunRequest, graph) -> RunState:
    """Legacy entry point — wraps the graph for backward compatibility."""
    run_id = str(uuid.uuid4())
    initial_state = {
        "thread_id": run_id,
        "run_id": run_id,
        "text": req.text,
        "flow": req.flow,
        "project_key": req.project_key,
        "skip_project_validation": True,
    }
    final_state = await graph.ainvoke(initial_state, _config(run_id))
    return to_run_state(final_state)


async def get_run_state(run_id: str, graph) -> RunState | None:
    snapshot = await graph.aget_state(_config(run_id))
    if not snapshot or not snapshot.values:
        return None
    return to_run_state(snapshot.values)
