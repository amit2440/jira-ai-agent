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

    # ── Retrieval ───────────────────────────────────────────────────────────────
    retrieved_documents: list[dict[str, Any]]
    enhanced_text: str | None   # post requirement-enhancement text (ticket flow)
    jql_query: str | None       # generated JQL string (jira_qa flow)

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
