from __future__ import annotations

from typing import Any, Literal, TypedDict


class GraphState(TypedDict, total=False):
    # ── Run identity ────────────────────────────────────────────────────────────
    thread_id: str
    run_id: str

    # ── Input ───────────────────────────────────────────────────────────────────
    text: str
    flow: Literal["rag_qa", "jira_qa", "hybrid_qa", "ticket", "report"] | None
    project_key: str

    # ── Pipeline state ──────────────────────────────────────────────────────────
    status: Literal["running", "awaiting_approval", "completed", "rejected", "failed"]
    router_decision: str | None
    skip_project_validation: bool   # legacy /api/runs entry point never validated project_key

    # ── Retrieval ───────────────────────────────────────────────────────────────
    retrieved_documents: list[dict[str, Any]]
    brd_docs: list[dict[str, Any]]   # react_retrieval split — BRD half, consumed by rag/hybrid agents
    jira_docs: list[dict[str, Any]]  # react_retrieval split — Jira half, consumed by jira/hybrid agents
    enhanced_text: str | None   # post requirement-enhancement text (ticket flow)
    grounded_requirement: str | None  # BRD-grounded rewrite from contradiction_check (ticket flow)
    contradictions: list[dict[str, Any]]
    ambiguities: list[dict[str, Any]]
    jql_query: str | None       # generated JQL string (jira_qa flow)

    # ── Report pipeline scratch (report flow) ─────────────────────────────────────
    plan: dict[str, Any]
    report: dict[str, Any]

    # ── LLM / action output ─────────────────────────────────────────────────────
    result: dict[str, Any]
    events: list[dict[str, Any]]

    # ── Error handling ──────────────────────────────────────────────────────────
    error: str | None

    # ── Human-in-the-loop ───────────────────────────────────────────────────────
    approved: bool
    feedback: str | None

    # ── Reflection loop + confidence check (report flow) ────────────────────────
    revision_count: int          # writer→reviewer iterations completed
    quality_score: float         # reviewer score 0.0–1.0 from last review
    reviewer_feedback: str       # concatenated reviewer notes passed back to writer
    quality_warning: bool        # True when quality < 0.85 after all revisions — triggers interrupt

    # ── Conversational memory ───────────────────────────────────────────────────
    session_id: str | None          # stable across turns in the same session
    conversation_history: list      # prior turns [{role, content, flow, timestamp}]

    # ── Observability ───────────────────────────────────────────────────────────
    model: str | None
    total_tokens: int
    prompt_version: str
    llm_params: dict[str, Any] | None

    # ── Gap-cycling (ticket flow, chat continuity) ────────────────────────────────
    pending_gaps: list[str]
    pending_topic: str
