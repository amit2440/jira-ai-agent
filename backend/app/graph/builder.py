"""LangGraph topology for the AI Requirements Assistant — 5-flow architecture.

Five agent flows
────────────────
  rag_qa     — BRD / knowledge Q&A            (immediate, no approval)
  jira_qa    — Live Jira data Q&A via NL→JQL  (immediate, no approval)
  hybrid_qa  — BRD + Jira gap analysis        (immediate, no approval)
  ticket     — Draft → human approval → Jira  (human-in-the-loop)
  report     — Plan → write → review → reflection loop → confidence check → approval → export

This graph IS the execution engine — `graph.invoke()` / `.stream()` drive every
flow. Nodes rehydrate a `RunState` from the incoming `GraphState` dict (see
`bridge.py`) so the existing `agents/*.py` and `logging/logger.py` functions —
which do attribute access (`run.x`) — run unmodified, then dump the mutated
object back into the returned partial state update.

Decision points
───────────────
  pii_validation    → "project_validation" (safe) | END (PII detected)
  project_validation → "router" (known project) | END (unknown project)
  router            → one of three entry nodes based on state["flow"]
  react_retrieval   → the matching *_qa_agent node for the classified flow
  reflection_check  → "writer" (quality < 0.90 AND revisions < 2) |
                      "confidence_check" (quality >= 0.90 OR max revisions reached)
  confidence_check  → "human_approval" (quality < 0.90 — interrupt with warning) |
                      "human_approval" (quality >= 0.90 — auto-continue, no warning)
  human_approval    → interrupt(); on resume: "jira_tool" (ticket approved) |
                      "report_export" (report approved) | "logging" (rejected)
"""
from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..agents.qa import answer_from_jira, answer_from_rag, answer_hybrid, expand_query
from ..agents.report import plan_report, review_report, write_report
from ..agents.router import route_request
from ..agents.ticket import detect_contradictions, enhance_requirement, generate_ticket
from ..config import operating_mode
from ..database import has_project_brd, log_execution
from ..logging.logger import (
    append_event,
    log_approval,
    log_context_snapshot,
    log_decision,
    log_error,
    log_finalize,
    log_retrieval,
    log_run_end,
    log_run_start,
    log_state,
    log_tool,
    track_node,
)
from ..memory import format_history_for_prompt
from ..models import TimelineEvent
from ..retrievers.vector import has_project_vectors
from ..tools.export import report_export as export_report_tool
from ..tools.jira import jira_create_ticket, jira_project_exists, jira_project_health
from ..tools.pii import pii_validator
from ..tools.retrieval import hybrid_search_tool
from .bridge import add_tokens, from_run_state, to_run_state
from .react_agent import run_retrieval_react
from .state import GraphState

_QUALITY_THRESHOLD = 0.90
_MAX_REVISIONS = 2


# ── Gate nodes ────────────────────────────────────────────────────────────────────

def _pii_validation(state: GraphState) -> dict:
    run = to_run_state(state)
    log_run_start(run)
    log_state(run, "CHAT_INTAKE", mode=operating_mode(), project_key=run.project_key)
    pii = pii_validator(run.text)
    log_tool(run, "pii_validator", f"safe={pii['safe']}", findings=pii.get("findings", []))
    if not pii["safe"]:
        run.status = "failed"
        run.error = "PII detected in your message. Please remove personal data and try again."
        log_error(run, "pii_validation", run.error)
        log_run_end(run)
    return from_run_state(run)


def _project_validation(state: GraphState) -> dict:
    run = to_run_state(state)
    if state.get("skip_project_validation"):
        return {}
    key = run.project_key
    with track_node(run, "project_validation", f"Validating project key '{key}'", "tool"):
        brd_ok = has_project_brd(key) or has_project_vectors(key)
        jira_ok = jira_project_exists(key)
        run.events[-1].detail.update({"project_key": key, "brd_found": brd_ok, "jira_found": jira_ok})
    log_tool(run, "project_validation", f"project={key!r} brd={brd_ok} jira={jira_ok}",
             brd_found=brd_ok, jira_found=jira_ok)

    if not brd_ok and not jira_ok:
        hints = []
        if not brd_ok:
            hints.append(f"BRD: no documents tagged '{key}' — run scripts/ingest_brd.py --project-key {key}")
        if not jira_ok:
            hints.append(f"Jira: project '{key}' not found — verify the key in your Jira workspace")
        run.status = "failed"
        run.error = f"Project '{key}' not recognised. " + " | ".join(hints)
        log_error(run, "project_validation", run.error)
        log_run_end(run)
    return from_run_state(run)


def _router(state: GraphState) -> dict:
    run = to_run_state(state)
    forced = state.get("flow")
    with track_node(run, "router", "Request routed", "router") as event:
        routing = route_request(run.text, forced_flow=forced, _run=run)
        run.flow = routing["flow"]
        run.router_decision = routing["flow"]
        add_tokens(run, routing)
        event.message = f"Routed to {run.flow}"
        event.detail.update({"reason": routing["reason"], "model": routing["model"]})
    log_decision(run, "router", run.flow, routing["reason"])
    log_state(run, "POST_ROUTER", flow=run.flow)
    log_context_snapshot(run, "POST_ROUTER")
    return from_run_state(run)


# ── Q&A flow nodes ──────────────────────────────────────────────────────────────

def _react_retrieval(state: GraphState) -> dict:
    """Dynamic ReAct tool selection — shared by rag_qa/jira_qa/hybrid_qa."""
    run = to_run_state(state)
    log_state(run, f"{run.flow.upper()}_START")
    with track_node(run, "react_retrieval", f"ReAct tool selection ({run.flow})", "tool") as ev:
        brd_docs, jira_docs, react_meta = run_retrieval_react(
            run.text, project_key=run.project_key, flow_hint=run.flow, _run=run,
        )
        add_tokens(run, react_meta)

        queries = [run.text]
        if run.flow in ("rag_qa", "hybrid_qa") and brd_docs is not None:
            queries = expand_query(run.text, _run=run)
            if len(queries) > 1:
                seen: dict[str, dict] = {(d.get("id") or d.get("title")): d for d in brd_docs}
                for q in queries[1:]:
                    for doc in hybrid_search_tool(q, limit=8, project_key=run.project_key):
                        key = doc.get("id") or doc.get("title")
                        if key not in seen or doc.get("score", 0) > seen[key].get("score", 0):
                            seen[key] = doc
                brd_docs = sorted(seen.values(), key=lambda d: d.get("rerank_score", d.get("score", 0)), reverse=True)[:8]

        run.retrieved_documents = brd_docs + jira_docs
        ev.detail.update({
            "brd_docs": len(brd_docs),
            "jira_docs": len(jira_docs),
            "flow_hint": run.flow,
            "query_variants": len(queries) if run.flow in ("rag_qa", "hybrid_qa") else 1,
        })
    log_retrieval(run, len(run.retrieved_documents), "react_retrieval",
                  titles=[d.get("title", "") for d in run.retrieved_documents[:8]])
    updates = from_run_state(run)
    updates["brd_docs"] = brd_docs
    updates["jira_docs"] = jira_docs
    return updates


def _rag_qa_agent(state: GraphState) -> dict:
    run = to_run_state(state)
    brd_docs = state.get("brd_docs") or []
    history_prompt = format_history_for_prompt(state.get("conversation_history") or [], max_turns=6)
    with track_node(run, "rag_qa_agent", "RAG answer generated", "function") as ev:
        payload, meta = answer_from_rag(
            run.text, brd_docs, _run=run, project_key=run.project_key, history=history_prompt,
        )
        add_tokens(run, meta)
        ev.detail["confidence"] = payload.get("confidence", "high")
        ev.detail["sources_count"] = len(payload.get("sources_used", []))
    run.result = {"answer": payload}
    run.status = "completed"
    log_state(run, "RAG_QA_DONE", confidence=payload.get("confidence"))
    log_context_snapshot(run, "RAG_QA_DONE")
    log_finalize(run)
    return from_run_state(run)


def _jira_qa_agent(state: GraphState) -> dict:
    run = to_run_state(state)
    jira_docs = state.get("jira_docs") or []
    history_prompt = format_history_for_prompt(state.get("conversation_history") or [], max_turns=6)
    with track_node(run, "jira_qa_agent", "Jira Q&A answer generated", "function") as ev:
        payload, meta = answer_from_jira(
            run.text, jira_docs, _run=run, project_key=run.project_key, history=history_prompt,
        )
        add_tokens(run, meta)
        ev.detail["confidence"] = payload.get("confidence", "medium")
    run.result = {"answer": payload}
    run.status = "completed"
    log_state(run, "JIRA_QA_DONE", confidence=payload.get("confidence"))
    log_context_snapshot(run, "JIRA_QA_DONE")
    log_finalize(run)
    return from_run_state(run)


def _hybrid_qa_agent(state: GraphState) -> dict:
    run = to_run_state(state)
    brd_docs = state.get("brd_docs") or []
    jira_docs = state.get("jira_docs") or []
    history_prompt = format_history_for_prompt(state.get("conversation_history") or [], max_turns=6)
    with track_node(run, "hybrid_qa_agent", "Hybrid gap analysis generated", "function") as ev:
        payload, meta = answer_hybrid(
            run.text, brd_docs, jira_docs, _run=run, project_key=run.project_key, history=history_prompt,
        )
        add_tokens(run, meta)
        ev.detail["confidence"] = payload.get("confidence", "medium")
        ev.detail["gaps"] = len(payload.get("gaps", []))
    run.result = {"answer": payload}
    run.status = "completed"
    log_state(run, "HYBRID_QA_DONE", confidence=payload.get("confidence"))
    log_context_snapshot(run, "HYBRID_QA_DONE")
    log_finalize(run)
    return from_run_state(run)


# ── Ticket flow nodes ────────────────────────────────────────────────────────────

def _requirement_enhancement(state: GraphState) -> dict:
    run = to_run_state(state)
    log_state(run, "TICKET_ENHANCE")
    with track_node(run, "requirement_enhancement", "Requirement enhanced", "function"):
        enhanced, meta = enhance_requirement(run.text, _run=run)
        add_tokens(run, meta)
    updates = from_run_state(run)
    updates["enhanced_text"] = enhanced
    return updates


def _ticket_retrieval(state: GraphState) -> dict:
    run = to_run_state(state)
    with track_node(run, "retrieval", "BRD documents retrieved (expanded + reranked)", "tool") as ev:
        queries = expand_query(run.text, _run=run)
        seen: dict[str, dict] = {}
        for q in queries:
            for doc in hybrid_search_tool(q, limit=8, project_key=run.project_key):
                key = doc.get("id") or doc.get("title")
                if key not in seen or doc.get("score", 0) > seen[key].get("score", 0):
                    seen[key] = doc
        run.retrieved_documents = sorted(seen.values(), key=lambda d: d.get("rerank_score", d.get("score", 0)), reverse=True)[:8]
        ev.detail["documents"] = [{"title": d["title"]} for d in run.retrieved_documents]
        ev.detail["query_variants"] = len(queries)
    log_retrieval(run, len(run.retrieved_documents), "hybrid_rag",
                  titles=[d["title"] for d in run.retrieved_documents])
    return from_run_state(run)


def _contradiction_check(state: GraphState) -> dict:
    run = to_run_state(state)
    enhanced = state.get("enhanced_text") or run.text
    with track_node(run, "contradiction_check", "Requirement checked against BRD", "function") as ev:
        contradiction_analysis, c_meta = detect_contradictions(enhanced, run.retrieved_documents, _run=run)
        add_tokens(run, c_meta)
        contradictions = contradiction_analysis.get("contradictions", [])
        ambiguities = contradiction_analysis.get("ambiguities", [])
        ev.detail.update({
            "contradictions_found": len(contradictions),
            "ambiguities_found": len(ambiguities),
            "clarification_needed": contradiction_analysis.get("clarification_needed", False),
        })
        grounded_text = contradiction_analysis.get("grounded_requirement", enhanced)
    log_decision(
        run, "contradiction_check",
        f"contradictions={len(contradictions)} ambiguities={len(ambiguities)}",
        "proceed" if not contradiction_analysis.get("clarification_needed") else "warn",
    )
    updates = from_run_state(run)
    updates["grounded_requirement"] = grounded_text
    updates["contradictions"] = contradictions
    updates["ambiguities"] = ambiguities
    return updates


def _ticket_generation(state: GraphState) -> dict:
    run = to_run_state(state)
    grounded_text = state.get("grounded_requirement") or run.text
    contradictions = state.get("contradictions") or []
    ambiguities = state.get("ambiguities") or []
    log_state(run, "TICKET_GENERATE")
    with track_node(run, "ticket_generation", "Ticket draft ready", "function") as ev:
        ticket, meta = generate_ticket(grounded_text, run.retrieved_documents, _run=run)
        ticket["_contradictions"] = contradictions
        ticket["_ambiguities"] = ambiguities
        run.result = {"ticket": ticket}
        add_tokens(run, meta)
        ev.detail["confidence"] = ticket.get("confidence", "medium")
        ev.detail["ac_count"] = len(ticket.get("acceptance_criteria", []))
        ev.detail["brd_coverage"] = ticket.get("brd_coverage", [])
        ev.detail["contradictions_found"] = len(contradictions)
    log_state(run, "TICKET_GENERATED",
              summary=ticket.get("summary", "")[:80],
              issue_type=ticket.get("issue_type"),
              priority=ticket.get("priority"))
    run.status = "awaiting_approval"
    log_state(run, "AWAITING_APPROVAL", total_tokens=run.total_tokens)
    append_event(run, "human_approval", "Ticket draft awaiting human approval", "approval")
    return from_run_state(run)


# ── Report flow nodes ────────────────────────────────────────────────────────────

def _jira_health(state: GraphState) -> dict:
    run = to_run_state(state)
    with track_node(run, "retrieval", "Jira health metrics retrieved", "tool"):
        run.retrieved_documents = jira_project_health(run.project_key)
    log_retrieval(run, len(run.retrieved_documents), "jira_project_health")
    return from_run_state(run)


def _planner(state: GraphState) -> dict:
    run = to_run_state(state)
    log_state(run, "REPORT_PLAN")
    with track_node(run, "planner", "Report plan created", "function"):
        plan, meta = plan_report(run.text, run.retrieved_documents, _run=run)
        add_tokens(run, meta)
    updates = from_run_state(run)
    updates["plan"] = plan
    return updates


def _writer(state: GraphState) -> dict:
    run = to_run_state(state)
    plan = state.get("plan") or {}
    revision = state.get("revision_count", 0)
    reviewer_feedback = state.get("reviewer_feedback", "")
    log_state(run, "REPORT_WRITE", revision=revision)
    with track_node(run, "writer", f"Report draft written (revision {revision})", "function"):
        report, meta = write_report(
            run.text, plan, run.retrieved_documents, _run=run, feedback=reviewer_feedback,
        )
        add_tokens(run, meta)
    updates = from_run_state(run)
    updates["report"] = report
    return updates


def _reviewer(state: GraphState) -> dict:
    run = to_run_state(state)
    report = state.get("report") or {}
    revision = state.get("revision_count", 0)
    log_state(run, "REPORT_REVIEW", revision=revision)
    with track_node(run, "reviewer", f"Review completed (revision {revision})", "function"):
        report, meta = review_report(report, _run=run)
        add_tokens(run, meta)
    updates = from_run_state(run)
    updates["report"] = report
    updates["quality_score"] = report.get("quality_score", _QUALITY_THRESHOLD)
    return updates


def _reflection_check(state: GraphState) -> dict:
    run = to_run_state(state)
    report = state.get("report") or {}
    revision = state.get("revision_count", 0)
    quality_score = report.get("quality_score", _QUALITY_THRESHOLD)
    reviewer_feedback = "\n".join(report.get("review_notes", []))

    looping = quality_score < _QUALITY_THRESHOLD and revision < _MAX_REVISIONS
    log_decision(
        run, "reflection_check",
        f"revision={revision} quality={quality_score:.2f} threshold={_QUALITY_THRESHOLD}",
        "writer" if looping else "confidence_check",
    )
    append_event(
        run, "reflection_check",
        f"Quality {quality_score:.2f} — {'loop back to writer' if looping else 'exit to confidence check'}",
        "node", quality_score=quality_score, revision=revision,
        decision="writer" if looping else "confidence_check",
    )

    new_revision = revision
    if looping:
        new_revision = revision + 1
        append_event(
            run, "revision",
            f"Revision {new_revision} triggered — quality {quality_score:.2f} below {_QUALITY_THRESHOLD}",
            "node",
        )

    updates = from_run_state(run)
    updates["quality_score"] = quality_score
    updates["reviewer_feedback"] = reviewer_feedback
    updates["revision_count"] = new_revision
    return updates


def _confidence_check(state: GraphState) -> dict:
    run = to_run_state(state)
    report = state.get("report") or {}
    revision = state.get("revision_count", 0)
    quality_score = report.get("quality_score", _QUALITY_THRESHOLD)
    quality_warning = quality_score < _QUALITY_THRESHOLD
    outcome = "interrupt — human review required" if quality_warning else "auto-continue"

    log_decision(
        run, "confidence_check",
        f"quality={quality_score:.2f} revisions_used={revision} threshold={_QUALITY_THRESHOLD}",
        outcome,
    )
    append_event(
        run, "confidence_check",
        f"Quality {quality_score:.2f} after {revision} revision(s) — {outcome}",
        "node", quality_score=quality_score, quality_warning=quality_warning,
        revisions_used=revision, threshold=_QUALITY_THRESHOLD,
    )

    run.result = {
        "report": report,
        "quality_score": quality_score,
        "quality_warning": quality_warning,
        "review_notes": report.get("review_notes", []),
    }
    run.status = "awaiting_approval"
    log_state(run, "AWAITING_APPROVAL", total_tokens=run.total_tokens, revisions=revision,
              quality_score=quality_score, quality_warning=quality_warning)
    append_event(run, "human_approval", "Report draft awaiting human approval", "approval")

    updates = from_run_state(run)
    updates["quality_warning"] = quality_warning
    return updates


# ── Shared action / post-processing nodes ────────────────────────────────────────

def _human_approval(state: GraphState) -> dict:
    """Interrupt point — execution pauses until resumed with Command(resume={approved, feedback})."""
    run = to_run_state(state)
    payload = interrupt({"flow": run.flow, "draft": run.result, "run_id": run.run_id})
    approved = bool(payload.get("approved")) if isinstance(payload, dict) else bool(payload)
    feedback = payload.get("feedback") if isinstance(payload, dict) else None

    log_approval(run, approved, feedback or "")
    log_state(run, "APPROVAL_RECEIVED", approved=approved)
    if not approved:
        run.status = "rejected"
    run.events.append(TimelineEvent(
        node="human_feedback", kind="approval",
        message="Approved" if approved else "Rejected",
        detail={"approved": approved, "feedback": feedback or ""},
    ))

    updates = from_run_state(run)
    updates["approved"] = approved
    updates["feedback"] = feedback
    return updates


def _jira_tool(state: GraphState) -> dict:
    run = to_run_state(state)
    log_state(run, "JIRA_CREATE", project_key=run.project_key)
    with track_node(run, "jira_create_ticket", "Jira issue created", "tool"):
        out = jira_create_ticket(run.result.get("ticket", {}), project_key=run.project_key)
        run.result["jira"] = out
        run.events[-1].detail.update(out)
        log_execution(run_id=run.run_id, thread_id=run.thread_id,
                      node="jira_create_ticket", function_name="jira_create_ticket",
                      tool="jira_create_ticket", payload=out)
    log_tool(run, "jira_create_ticket", f"status={out.get('status')}",
             key=out.get("key"), url=out.get("url"))

    if out.get("status") == "failed":
        run.status = "failed"
        run.error = out.get("error", "Unknown Jira error")
        log_error(run, "jira_create_ticket", run.error)
        return from_run_state(run)

    run.status = "completed"
    return from_run_state(run)


def _report_export(state: GraphState) -> dict:
    run = to_run_state(state)
    log_state(run, "REPORT_EXPORT")
    with track_node(run, "report_export", "Report exported", "tool"):
        out = export_report_tool(run.result.get("report", {}), run.run_id)
        run.result["export"] = out
        log_execution(run_id=run.run_id, thread_id=run.thread_id,
                      node="report_export", function_name="report_export",
                      tool="report_export", payload=out)
    log_tool(run, "report_export", f"path={out.get('path')}")
    run.status = "completed"
    return from_run_state(run)


def _logging(state: GraphState) -> dict:
    """Final node for every path — persists the trace and closes the run."""
    run = to_run_state(state)
    if run.status == "rejected":
        log_state(run, "REJECTED")
    elif run.status == "completed" and run.flow in ("ticket", "report"):
        log_finalize(run)
        append_event(run, "logging", "Execution finalized", "node", total_tokens=run.total_tokens)
        log_context_snapshot(run, "COMPLETED")
    log_run_end(run)
    return from_run_state(run)


# ── Conditional edge functions ────────────────────────────────────────────────────

def _after_pii(state: GraphState) -> Literal["project_validation", "__end__"]:
    return "__end__" if state.get("status") == "failed" else "project_validation"


def _after_project_validation(state: GraphState) -> Literal["router", "__end__"]:
    return "__end__" if state.get("status") == "failed" else "router"


def _after_router(state: GraphState) -> Literal["react_retrieval", "requirement_enhancement", "jira_health"]:
    return {
        "rag_qa":    "react_retrieval",
        "jira_qa":   "react_retrieval",
        "hybrid_qa": "react_retrieval",
        "ticket":    "requirement_enhancement",
        "report":    "jira_health",
    }.get(state.get("flow") or "rag_qa", "react_retrieval")


def _after_retrieval(state: GraphState) -> Literal["rag_qa_agent", "jira_qa_agent", "hybrid_qa_agent"]:
    return {
        "rag_qa":    "rag_qa_agent",
        "jira_qa":   "jira_qa_agent",
        "hybrid_qa": "hybrid_qa_agent",
    }.get(state.get("flow") or "rag_qa", "rag_qa_agent")


def _after_reflection(state: GraphState) -> Literal["writer", "confidence_check"]:
    quality = state.get("quality_score", 1.0)
    revision = state.get("revision_count", 0)
    if quality < _QUALITY_THRESHOLD and revision < _MAX_REVISIONS:
        return "writer"
    return "confidence_check"


def _after_confidence(state: GraphState) -> Literal["human_approval_interrupt", "human_approval_continue"]:
    quality = state.get("quality_score", 1.0)
    if quality < _QUALITY_THRESHOLD:
        return "human_approval_interrupt"
    return "human_approval_continue"


def _after_approval(state: GraphState) -> Literal["jira_tool", "report_export", "logging"]:
    if not state.get("approved"):
        return "logging"
    return "jira_tool" if state.get("flow") == "ticket" else "report_export"


# ── Graph assembly ────────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    graph = StateGraph(GraphState)

    graph.add_node("pii_validation",          _pii_validation)
    graph.add_node("project_validation",      _project_validation)
    graph.add_node("router",                  _router)

    # Q&A flows
    graph.add_node("react_retrieval",         _react_retrieval)
    graph.add_node("rag_qa_agent",            _rag_qa_agent)
    graph.add_node("jira_qa_agent",           _jira_qa_agent)
    graph.add_node("hybrid_qa_agent",         _hybrid_qa_agent)

    # Ticket flow
    graph.add_node("requirement_enhancement", _requirement_enhancement)
    graph.add_node("ticket_retrieval",        _ticket_retrieval)
    graph.add_node("contradiction_check",     _contradiction_check)
    graph.add_node("ticket_generation",       _ticket_generation)

    # Report flow
    graph.add_node("jira_health",             _jira_health)
    graph.add_node("planner",                 _planner)
    graph.add_node("writer",                  _writer)
    graph.add_node("reviewer",                _reviewer)
    graph.add_node("reflection_check",        _reflection_check)
    graph.add_node("confidence_check",        _confidence_check)

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

    graph.add_conditional_edges("router", _after_router)

    # ── Q&A ──
    graph.add_conditional_edges("react_retrieval", _after_retrieval)
    graph.add_edge("rag_qa_agent",     "logging")
    graph.add_edge("jira_qa_agent",    "logging")
    graph.add_edge("hybrid_qa_agent",  "logging")

    # ── Ticket flow ──
    graph.add_edge("requirement_enhancement", "ticket_retrieval")
    graph.add_edge("ticket_retrieval",        "contradiction_check")
    graph.add_edge("contradiction_check",     "ticket_generation")
    graph.add_edge("ticket_generation",       "human_approval")

    # ── Report flow (reflection loop + confidence check) ──
    graph.add_edge("jira_health",      "planner")
    graph.add_edge("planner",          "writer")
    graph.add_edge("writer",           "reviewer")
    graph.add_edge("reviewer",         "reflection_check")
    graph.add_conditional_edges("reflection_check", _after_reflection, {
        "writer":           "writer",
        "confidence_check": "confidence_check",
    })
    graph.add_conditional_edges("confidence_check", _after_confidence, {
        "human_approval_interrupt": "human_approval",
        "human_approval_continue":  "human_approval",
    })

    # ── Approval gate (shared by ticket + report) ──
    graph.add_conditional_edges("human_approval", _after_approval)

    graph.add_edge("jira_tool",     "logging")
    graph.add_edge("report_export", "logging")
    graph.add_edge("logging",       END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
