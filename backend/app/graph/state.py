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

    # ── Observability ───────────────────────────────────────────────────────────
    model: str | None
    total_tokens: int
    prompt_version: str
