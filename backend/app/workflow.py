"""
Orchestration workflow — supports 5 agent flows:

  rag_qa     — immediate BRD Q&A (no approval)
  jira_qa    — immediate Jira Q&A (no approval, uses NL→JQL)
  hybrid_qa  — immediate BRD + Jira gap analysis (no approval)
  ticket     — generate draft → human approval → create in Jira
  report     — generate draft → human approval → export

Entry points:
  chat(req)           — unified chat interface (auto-routes)
  start(req)          — legacy /api/runs entry point (backward compat)
  approve(run, ...)   — human approval for ticket/report flows

All stages are fully logged with thread_id, state snapshots, and LLM traces.
"""
from __future__ import annotations

import uuid
from typing import Any

try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree as _get_ls_run
except ImportError:
    def traceable(**_):  # type: ignore[misc]
        def _wrap(fn):
            return fn
        return _wrap
    _get_ls_run = lambda: None  # type: ignore[assignment]


def _stamp_ls_metadata(run: "RunState") -> None:
    """Inject run identity into the active LangSmith trace so threads are linkable."""
    try:
        rt = _get_ls_run()
        if rt is not None:
            rt.metadata.update({
                "thread_id": run.thread_id,
                "run_id":    run.run_id,
                "project_key": run.project_key,
                "flow":      run.flow,
            })
    except Exception:
        pass

from .agents.qa import answer_from_jira, answer_from_rag, answer_hybrid, nl_to_jql
from .agents.report import plan_report, review_report, write_report
from .agents.router import route_request
from .agents.ticket import enhance_requirement, generate_ticket
from .config import JIRA_PROJECT_KEY, operating_mode
from .database import has_project_brd, log_execution, save_run
from .retrievers.vector import has_project_vectors
from .logging.logger import (
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
    log_warning,
    track_node,
)
from .models import ChatRequest, ChatResponse, RunRequest, RunState, SourceRef
from .tools.export import report_export
from .tools.jira import jira_create_ticket, jira_project_exists, jira_project_health, jira_search
from .tools.pii import pii_validator
from .tools.retrieval import hybrid_search_tool
from .tools.state import human_feedback

# Projects the report flow is scoped to. Non-matching projects return an error.
ALLOWED_REPORT_PROJECTS = {"EOMS"}


def _add_tokens(run: RunState, meta: dict[str, Any]) -> None:
    usage = meta.get("token_usage", {})
    run.total_tokens += int(usage.get("total_tokens", 0))
    if meta.get("model"):
        run.model = meta["model"]
    if usage and run.events:
        run.events[-1].detail["token_usage"] = {
            "prompt_tokens":     usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens":      usage.get("total_tokens", 0),
        }


def _make_source_refs(docs: list[dict[str, Any]], source: str = "knowledge") -> list[SourceRef]:
    return [
        SourceRef(
            title=d.get("title", "Document"),
            content=d.get("content", "")[:500],
            score=d.get("score"),
            bm25_score=d.get("bm25_score"),
            vector_score=d.get("vector_score"),
            source=source,
        )
        for d in docs
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT VALIDATION NODE
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_project(run: "RunState") -> "ChatResponse | None":
    """
    Gate before router: verify the project key exists in BRD corpus AND/OR live Jira.
    - brd_ok  : SQLite has tagged docs OR Chroma has tagged chunks for this key
    - jira_ok : Jira REST confirms the project key exists (skipped in demo mode)
    Fails fast if neither source recognises the project key.
    """
    key = run.project_key
    with track_node(run, "project_validation", f"Validating project key '{key}'", "tool"):
        brd_ok  = has_project_brd(key) or has_project_vectors(key)
        jira_ok = jira_project_exists(key)   # GET /rest/api/3/project/{key} — real 200/404

        run.events[-1].detail.update({
            "project_key": key,
            "brd_found":  brd_ok,
            "jira_found": jira_ok,
        })

    log_tool(run, "project_validation",
             f"project={key!r} brd={brd_ok} jira={jira_ok}",
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
        save_run(run)
        log_run_end(run)
        return ChatResponse(
            run_id=run.run_id, thread_id=run.thread_id,
            flow="rag_qa", status="failed", error=run.error,
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED CHAT ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def chat(req: ChatRequest) -> ChatResponse:
    """
    Unified entry point for the chat interface.
    Routes to the correct flow and returns either an immediate answer (Q&A flows)
    or a draft awaiting approval (ticket/report flows).
    """
    run = RunState(
        thread_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        text=req.text,
        flow=None,
        project_key=(req.project_key or JIRA_PROJECT_KEY or "EOMS").upper(),
        llm_params=req.llm_params
    )

    log_run_start(run)
    log_state(run, "CHAT_INTAKE", mode=operating_mode(), project_key=run.project_key)
    save_run(run)

    # ── PII VALIDATION ────────────────────────────────────────────────
    pii = pii_validator(run.text)
    log_tool(run, "pii_validator", f"safe={pii['safe']}", findings=pii.get("findings", []))
    if not pii["safe"]:
        run.status = "failed"
        run.error = "PII detected in your message. Please remove personal data and try again."
        log_error(run, "pii_validation", run.error)
        save_run(run)
        log_run_end(run)
        return ChatResponse(
            run_id=run.run_id, thread_id=run.thread_id,
            flow="rag_qa", status="failed", error=run.error,
        )

    # ── PROJECT VALIDATION ────────────────────────────────────────────
    validation_err = _validate_project(run)
    if validation_err:
        return validation_err

    # ── ROUTER ────────────────────────────────────────────────────────
    with track_node(run, "router", "Request routed", "router") as event:
        routing = route_request(run.text, _run=run)
        run.flow = routing["flow"]
        run.router_decision = routing["flow"]
        _add_tokens(run, routing)
        event.message = f"Routed to {run.flow}"
        event.detail.update({"reason": routing["reason"], "model": routing["model"]})
    log_decision(run, "router", run.flow, routing["reason"])
    log_state(run, "POST_ROUTER", flow=run.flow)
    log_context_snapshot(run, "POST_ROUTER")
    save_run(run)

    # ── DISPATCH ──────────────────────────────────────────────────────
    if run.flow == "rag_qa":
        return _rag_qa_flow(run)
    elif run.flow == "jira_qa":
        return _jira_qa_flow(run)
    elif run.flow == "hybrid_qa":
        return _hybrid_qa_flow(run)
    elif run.flow == "ticket":
        return _ticket_flow_as_chat(run)
    elif run.flow == "report":
        return _report_flow_as_chat(run)
    else:
        run.status = "failed"
        run.error = f"Unknown flow: {run.flow}"
        log_error(run, "dispatch", run.error)
        save_run(run)
        return ChatResponse(
            run_id=run.run_id, thread_id=run.thread_id,
            flow=run.flow, status="failed", error=run.error,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Q&A FLOWS (immediate, no approval)
# ═══════════════════════════════════════════════════════════════════════════════

@traceable(name="rag_qa_flow", run_type="chain")
def _rag_qa_flow(run: RunState) -> ChatResponse:
    """Answer from BRD knowledge documents via hybrid search."""
    _stamp_ls_metadata(run)
    log_state(run, "RAG_QA_START")
    with track_node(run, "brd_retrieval", "BRD documents retrieved (BM25 + vector)", "tool"):
        docs = hybrid_search_tool(run.text, limit=5, project_key=run.project_key)
        run.retrieved_documents = docs
        bm25_count   = sum(1 for d in docs if d.get("bm25_score") is not None)
        vector_count = sum(1 for d in docs if d.get("vector_score") is not None)
        run.events[-1].detail.update({
            "documents":    [{"title": d["title"], "score": d.get("score")} for d in docs],
            "total":        len(docs),
            "bm25_count":   bm25_count,
            "vector_count": vector_count,
        })
    log_retrieval(run, len(docs), "brd_retrieval", titles=[d["title"] for d in docs])

    with track_node(run, "rag_qa_agent", "RAG answer generated", "function"):
        payload, meta = answer_from_rag(run.text, docs, _run=run, project_key=run.project_key)
        _add_tokens(run, meta)
        run.result = {"answer": payload}

    run.status = "completed"
    log_state(run, "RAG_QA_DONE", confidence=payload.get("confidence"))
    log_context_snapshot(run, "RAG_QA_DONE")
    log_finalize(run)
    save_run(run)
    log_run_end(run)

    return ChatResponse(
        run_id=run.run_id, thread_id=run.thread_id,
        flow=run.flow, status="completed",
        answer=payload,
        sources=_make_source_refs(docs, "knowledge"),
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
    )


@traceable(name="jira_qa_flow", run_type="chain")
def _jira_qa_flow(run: RunState) -> ChatResponse:
    """Answer from live Jira data using NL→JQL."""
    _stamp_ls_metadata(run)
    log_state(run, "JIRA_QA_START")

    # Step 1: Convert question to JQL
    with track_node(run, "nl_to_jql", "JQL generated from question", "function"):
        jql, jql_explanation, nl_meta = nl_to_jql(run.text, run.project_key or "EOMS", _run=run)
        run.events[-1].detail.update({"jql": jql, "explanation": jql_explanation})
        _add_tokens(run, nl_meta)
    log_decision(run, "nl_to_jql", jql, jql_explanation)

    # Step 2: Execute JQL and get results
    with track_node(run, "jira_search", "Jira data retrieved", "tool"):
        jira_result = jira_search(jql, max_results=10)
        # Convert to doc format for the QA agent
        if jira_result.get("mode") == "demo" or "issues" in jira_result:
            issues = jira_result.get("issues", [])
            jira_docs = [
                {
                    "title": f"{i['key']}: {i['summary']}",
                    "content": f"Key: {i['key']} | Status: {i.get('status', 'Unknown')} | Summary: {i['summary']}",
                    "source": "jira",
                }
                for i in issues
            ]
        else:
            # Fallback to project health metrics
            jira_docs = jira_project_health(run.project_key)
        run.retrieved_documents = jira_docs
        run.events[-1].detail["records"] = len(jira_docs)
    log_retrieval(run, len(jira_docs), "jira_search", jql=jql)

    # Step 3: Synthesise answer
    with track_node(run, "jira_qa_agent", "Jira Q&A answer generated", "function"):
        payload, meta = answer_from_jira(run.text, jira_docs, _run=run, project_key=run.project_key)
        _add_tokens(run, meta)
        run.result = {"answer": payload}

    run.status = "completed"
    log_state(run, "JIRA_QA_DONE", confidence=payload.get("confidence"))
    log_finalize(run)
    save_run(run)
    log_run_end(run)

    return ChatResponse(
        run_id=run.run_id, thread_id=run.thread_id,
        flow=run.flow, status="completed",
        answer=payload,
        sources=_make_source_refs(jira_docs, "jira"),
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
    )


@traceable(name="hybrid_qa_flow", run_type="chain")
def _hybrid_qa_flow(run: RunState) -> ChatResponse:
    """Cross-reference BRD docs and Jira for implementation gap analysis."""
    _stamp_ls_metadata(run)
    log_state(run, "HYBRID_QA_START")

    # Step 1: BRD retrieval
    with track_node(run, "brd_retrieval", "BRD documents retrieved (BM25 + vector)", "tool"):
        brd_docs = hybrid_search_tool(run.text, limit=5, project_key=run.project_key)
        bm25_count   = sum(1 for d in brd_docs if d.get("bm25_score") is not None)
        vector_count = sum(1 for d in brd_docs if d.get("vector_score") is not None)
        run.events[-1].detail.update({
            "brd_count":    len(brd_docs),
            "total":        len(brd_docs),
            "bm25_count":   bm25_count,
            "vector_count": vector_count,
        })
    log_retrieval(run, len(brd_docs), "brd_retrieval", titles=[d["title"] for d in brd_docs])

    # Step 2: Jira retrieval (health metrics for broad context)
    with track_node(run, "jira_health", "Jira health metrics retrieved", "tool"):
        jira_docs = jira_project_health(run.project_key)
        run.events[-1].detail["jira_count"] = len(jira_docs)
    log_retrieval(run, len(jira_docs), "jira_project_health")

    run.retrieved_documents = brd_docs + jira_docs
    log_context_snapshot(run, "HYBRID_QA_RETRIEVED")

    # Step 3: Cross-reference and synthesise
    with track_node(run, "hybrid_qa_agent", "Hybrid gap analysis generated", "function"):
        payload, meta = answer_hybrid(run.text, brd_docs, jira_docs, _run=run, project_key=run.project_key)
        _add_tokens(run, meta)
        run.result = {"answer": payload}

    run.status = "completed"
    log_state(run, "HYBRID_QA_DONE",
              confidence=payload.get("confidence"),
              gaps=len(payload.get("gaps", [])))
    log_finalize(run)
    save_run(run)
    log_run_end(run)

    all_sources = _make_source_refs(brd_docs, "knowledge") + _make_source_refs(jira_docs, "jira")
    return ChatResponse(
        run_id=run.run_id, thread_id=run.thread_id,
        flow=run.flow, status="completed",
        answer=payload,
        sources=all_sources,
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ACTION FLOWS (via chat — return ChatResponse wrapping RunState)
# ═══════════════════════════════════════════════════════════════════════════════

def _ticket_flow_as_chat(run: RunState) -> ChatResponse:
    """Run ticket generation and return draft awaiting approval."""
    _run_ticket_pipeline(run)
    ticket = run.result.get("ticket", {})
    return ChatResponse(
        run_id=run.run_id, thread_id=run.thread_id,
        flow=run.flow, status=run.status,
        draft=run.result,
        sources=_make_source_refs(run.retrieved_documents, "knowledge"),
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
        error=run.error,
    )


def _report_flow_as_chat(run: RunState) -> ChatResponse:
    """Run report generation and return draft awaiting approval."""
    _run_report_pipeline(run)
    return ChatResponse(
        run_id=run.run_id, thread_id=run.thread_id,
        flow=run.flow, status=run.status,
        draft=run.result,
        sources=_make_source_refs(run.retrieved_documents, "jira"),
        events=run.events,
        model=run.model, total_tokens=run.total_tokens,
        error=run.error,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED PIPELINE IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@traceable(name="ticket_pipeline", run_type="chain")
def _run_ticket_pipeline(run: RunState) -> None:
    """Ticket generation pipeline — populates run in-place."""
    _stamp_ls_metadata(run)
    effective_project = (run.project_key or JIRA_PROJECT_KEY or "").upper()
    log_state(run, "TICKET_ENHANCE")
    with track_node(run, "retrieval", "BRD documents retrieved", "tool"):
        run.retrieved_documents = hybrid_search_tool(run.text)
        run.events[-1].detail["documents"] = [{"title": d["title"]} for d in run.retrieved_documents]
    log_retrieval(run, len(run.retrieved_documents), "hybrid_rag",
                  titles=[d["title"] for d in run.retrieved_documents])

    with track_node(run, "requirement_enhancement", "Requirement enhanced", "function"):
        enhanced, meta = enhance_requirement(run.text, _run=run)
        _add_tokens(run, meta)

    log_state(run, "TICKET_GENERATE")
    with track_node(run, "ticket_generation", "Ticket draft ready", "function"):
        ticket, meta = generate_ticket(enhanced, run.retrieved_documents, _run=run)
        run.result = {"ticket": ticket}
        _add_tokens(run, meta)

    log_state(run, "TICKET_GENERATED",
              summary=ticket.get("summary", "")[:80],
              issue_type=ticket.get("issue_type"),
              priority=ticket.get("priority"))
    run.status = "awaiting_approval"
    log_state(run, "AWAITING_APPROVAL", total_tokens=run.total_tokens)
    append_event(run, "human_approval", "Ticket draft awaiting human approval", "approval")
    save_run(run)


_QUALITY_THRESHOLD = 0.85
_MAX_REVISIONS = 2


@traceable(name="report_pipeline", run_type="chain")
def _run_report_pipeline(run: RunState) -> None:
    """Report generation pipeline with reflection loop — populates run in-place."""
    _stamp_ls_metadata(run)

    with track_node(run, "retrieval", "Jira health metrics retrieved", "tool"):
        run.retrieved_documents = jira_project_health(run.project_key)
    log_retrieval(run, len(run.retrieved_documents), "jira_project_health")

    log_state(run, "REPORT_PLAN")
    with track_node(run, "planner", "Report plan created", "function"):
        plan, meta = plan_report(run.text, run.retrieved_documents, _run=run)
        _add_tokens(run, meta)

    # ── REFLECTION LOOP: writer → reviewer → loop if quality < threshold ──────
    revision = 0
    reviewer_feedback = ""
    report: dict = {}

    while True:
        log_state(run, "REPORT_WRITE", revision=revision)
        with track_node(run, "writer", f"Report draft written (revision {revision})", "function"):
            report, meta = write_report(
                run.text, plan, run.retrieved_documents,
                _run=run, feedback=reviewer_feedback,
            )
            _add_tokens(run, meta)

        log_state(run, "REPORT_REVIEW", revision=revision)
        with track_node(run, "reviewer", f"Review completed (revision {revision})", "function"):
            report, meta = review_report(report, _run=run)
            _add_tokens(run, meta)

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
            "node",
            quality_score=quality_score,
            revision=revision,
            decision="writer" if looping else "confidence_check",
        )

        if not looping:
            break

        revision += 1
        append_event(
            run, "revision",
            f"Revision {revision} triggered — quality {quality_score:.2f} below {_QUALITY_THRESHOLD}",
            "node",
        )

    # ── CONFIDENCE CHECK: final quality gate after reflection loop exits ──────
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
        "node",
        quality_score=quality_score,
        quality_warning=quality_warning,
        revisions_used=revision,
        threshold=_QUALITY_THRESHOLD,
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
    save_run(run)


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL
# ═══════════════════════════════════════════════════════════════════════════════

def approve(run: RunState, approved: bool, feedback: str | None = None) -> RunState:
    log_approval(run, approved, feedback or "")
    log_state(run, "APPROVAL_RECEIVED", approved=approved)
    human_feedback(run, approved, feedback)

    if not approved:
        log_state(run, "REJECTED")
        log_run_end(run)
        return run

    if run.flow == "ticket":
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
            save_run(run)
            log_run_end(run)
            return run
    else:
        log_state(run, "REPORT_EXPORT")
        with track_node(run, "report_export", "Report exported", "tool"):
            out = report_export(run.result.get("report", {}), run.run_id)
            run.result["export"] = out
            log_execution(run_id=run.run_id, thread_id=run.thread_id,
                          node="report_export", function_name="report_export",
                          tool="report_export", payload=out)
        log_tool(run, "report_export", f"path={out.get('path')}")

    run.status = "completed"
    log_finalize(run)
    append_event(run, "logging", "Execution finalized", "node", total_tokens=run.total_tokens)
    log_context_snapshot(run, "COMPLETED")
    save_run(run)
    log_run_end(run)
    return run


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY /api/runs ENTRY POINT (backward compat)
# ═══════════════════════════════════════════════════════════════════════════════

def start(req: RunRequest) -> RunState:
    """Legacy entry point — wraps chat() for backward compatibility."""
    chat_req = ChatRequest(
        text=req.text,
        project_key=req.project_key,
    )
    # If flow was forced, convert to chat and set router to skip LLM
    run = RunState(
        thread_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        text=req.text,
        flow=req.flow,
        project_key=req.project_key,
    )

    log_run_start(run)
    log_state(run, "INTAKE", mode=operating_mode(), flow=req.flow, project_key=req.project_key)
    save_run(run)

    # PII check
    pii = pii_validator(run.text)
    log_tool(run, "pii_validator", f"safe={pii['safe']}")
    if not pii["safe"]:
        run.status = "failed"
        run.error = "PII detected. Remove personal data before continuing."
        log_error(run, "pii_validation", run.error)
        save_run(run)
        log_run_end(run)
        return run

    # Route
    routing = route_request(run.text, forced_flow=run.flow, _run=run)
    run.flow = routing["flow"]
    run.router_decision = routing["flow"]
    _add_tokens(run, routing)
    log_decision(run, "router", run.flow, routing["reason"])
    log_state(run, "POST_ROUTER", flow=run.flow)

    # Dispatch to appropriate pipeline
    if run.flow in ("rag_qa", "jira_qa", "hybrid_qa"):
        # Q&A flows — convert to chat and return embedded in run
        if run.flow == "rag_qa":
            docs = hybrid_search_tool(run.text)
            run.retrieved_documents = docs
            payload, meta = answer_from_rag(run.text, docs, _run=run, project_key=run.project_key)
        elif run.flow == "jira_qa":
            jira_docs = jira_project_health(run.project_key)
            run.retrieved_documents = jira_docs
            payload, meta = answer_from_jira(run.text, jira_docs, _run=run, project_key=run.project_key)
        else:
            brd_docs = hybrid_search_tool(run.text)
            jira_docs = jira_project_health(run.project_key)
            run.retrieved_documents = brd_docs + jira_docs
            payload, meta = answer_hybrid(run.text, brd_docs, jira_docs, _run=run, project_key=run.project_key)
        _add_tokens(run, meta)
        run.result = {"answer": payload}
        run.status = "completed"
        log_finalize(run)
        save_run(run)
        log_run_end(run)
        return run
    elif run.flow == "ticket":
        _run_ticket_pipeline(run)
    else:
        _run_report_pipeline(run)

    return run
