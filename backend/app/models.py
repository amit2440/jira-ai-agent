from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .prompts.templates import PROMPT_VERSION

# All supported agent flows
Flow = Literal["ticket", "report", "rag_qa", "jira_qa", "hybrid_qa"]
Status = Literal["running", "awaiting_approval", "completed", "rejected", "failed"]


class RunRequest(BaseModel):
    text: str = Field(min_length=8, max_length=12000)
    flow: Flow | None = None
    project_key: str | None = None


class LlmParams(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None
    # top_p and top_k omitted — no meaningful effect at low temperatures; Groq support inconsistent.


class PendingAction(BaseModel):
    """Tracks a deferred action the user can confirm with a short affirmative."""
    type: str                          # "generate_tickets"
    description: str                   # human-readable label shown in UI
    gaps: list[str] = Field(default_factory=list)   # missing requirement names
    topic: str = ""                    # category the gaps belong to (e.g. "security")


class ChatRequest(BaseModel):
    """Single-turn chat message. Router auto-selects the flow."""
    text: str = Field(min_length=2, max_length=12000)
    project_key: str | None = "EOMS"
    session_id: str | None = None  # Reserved for future multi-turn support
    llm_params: LlmParams | None = None
    pending_action: PendingAction | None = None  # set by frontend when user confirms a prior offer


class TimelineEvent(BaseModel):
    at: datetime = Field(default_factory=datetime.utcnow)
    node: str
    kind: str = "node"
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None


class RunState(BaseModel):
    thread_id: str
    run_id: str
    text: str
    flow: Flow | None = None
    project_key: str | None = None
    session_id: str | None = None          # stable across turns; used for conversation history
    status: Status = "running"
    router_decision: str | None = None
    prompt_version: str = PROMPT_VERSION
    retrieved_documents: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    events: list[TimelineEvent] = Field(default_factory=list)
    error: str | None = None
    model: str | None = None
    total_tokens: int = 0
    llm_params: LlmParams | None = None
    # set when cycling through per-gap ticket generation
    pending_gaps: list[str] = Field(default_factory=list)
    pending_topic: str = ""


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str | None = None


class KnowledgeDocument(BaseModel):
    id: str | None = None
    title: str
    content: str = Field(min_length=10)
    project_key: str | None = None


# ── Chat response models ───────────────────────────────────────────────────────

class SourceRef(BaseModel):
    """A retrieved document snippet used to ground a Q&A answer."""
    title: str
    content: str
    score: float | None = None
    bm25_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None
    source: str = "knowledge"  # "knowledge" | "jira"


class ChatResponse(BaseModel):
    """
    Unified response for both Q&A flows (immediate answer) and
    action flows (ticket/report — require human approval).
    """
    run_id: str
    thread_id: str
    flow: Flow
    status: Status

    # Q&A flows: populated immediately
    answer: dict[str, Any] | None = None
    sources: list[SourceRef] = Field(default_factory=list)

    # Action flows: populated when draft is ready
    draft: dict[str, Any] | None = None      # ticket dict or report dict
    events: list[TimelineEvent] = Field(default_factory=list)

    # Metadata
    model: str | None = None
    total_tokens: int = 0
    error: str | None = None

    # Conversation continuity — set when the answer ends with a follow-up offer
    pending_action: PendingAction | None = None
