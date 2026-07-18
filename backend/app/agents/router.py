"""
Router agent — classifies user intent into one of five flows:
  rag_qa     — question about BRD / knowledge documents
  jira_qa    — question about live Jira data (tickets, bugs, sprint)
  hybrid_qa  — cross-reference BRD + Jira (gap analysis, coverage)
  ticket     — create a new Jira ticket (requires human approval)
  report     — generate a project status report (requires human approval)

Heuristic fallback used when LLM is unavailable.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..prompts.templates import ROUTER_SYSTEM, router_prompt
from ..services.llm import invoke_json
from ..services.tokens import token_budget

_log = logging.getLogger("agent")

VALID_FLOWS = {"ticket", "report", "rag_qa", "jira_qa", "hybrid_qa"}


def _heuristic_flow(text: str) -> str:
    """Keyword-based fallback when LLM is unavailable."""
    t = text.lower()
    # Action flows (highest specificity first)
    if re.search(r"\b(create|add|draft|write)\b.{0,40}\b(ticket|story|task|issue|bug report)\b", t):
        return "ticket"
    if re.search(r"\b(status report|project report|generate.*report|sprint report)\b", t):
        return "report"
    # Hybrid gap/coverage analysis (before individual source checks)
    if re.search(
        r"\b(gap|missing|covered|coverage|alignment|is.*implemented|are.*implemented|"
        r"without.*ticket|brd.*jira|jira.*brd|requirements.*covered|tickets.*requirement)\b", t
    ):
        return "hybrid_qa"
    # Jira live-data questions: count/status queries + Jira-specific nouns
    if re.search(
        r"\b(how many|list|show|open|closed|in progress|to do|done|sprint|backlog|"
        r"blocker|assignee|story point|velocity)\b.{0,60}\b(ticket|issue|bug|story|task|defect|work|item)\b", t
    ):
        return "jira_qa"
    if re.search(r"\b(open bugs?|open defects?|open issues?|open tickets?)\b", t):
        return "jira_qa"
    if re.search(r"\b(jira|sprint|bug|defect|blocker|assignee|backlog|story point)\b", t):
        return "jira_qa"
    # BRD/requirements knowledge questions
    if re.search(
        r"\b(brd|requirement|spec|document|what does.*say|describe.*requirement|"
        r"according to|policy|guideline)\b", t
    ):
        return "rag_qa"
    # Default: BRD Q&A
    return "rag_qa"


def route_request(
    text: str,
    forced_flow: str | None = None,
    _run=None,
) -> dict[str, Any]:
    """
    Classify the user's intent into one of five agent flows.

    _run: optional RunState — if provided, thread_id is used in log tags.
    """
    tid = f"[THREAD:{_run.thread_id}]" if _run is not None else "[THREAD:no-run]"
    text_preview = text[:150].replace("\n", " ")
    budget = token_budget("extraction", text)

    # ── FORCED FLOW (rare — kept for backward compat with /api/runs) ──────────
    if forced_flow and forced_flow in VALID_FLOWS:
        _log.info(
            f"{tid} [ROUTER] Flow forced by caller: flow={forced_flow!r} — skipping LLM classification"
        )
        return {
            "flow": forced_flow,
            "reason": "Caller-specified flow",
            "model": "manual",
            "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }

    # ── LLM CLASSIFICATION ────────────────────────────────────────────────────
    _log.info(
        f"{tid} [ROUTER] Starting 5-way intent classification — "
        f"preview={text_preview!r} token_budget={budget}"
    )
    _log.debug(f"{tid} [ROUTER] Full intent text ({len(text)} chars):\n{text[:1000]}")

    try:
        _log.debug(f"{tid} [ROUTER] Dispatching to LLM for 5-way classification…")
        payload, meta = invoke_json(
            router_prompt(text),
            task="extraction",
            max_tokens=budget,
            system=ROUTER_SYSTEM,
            _agent_tag="router",
            _run=_run,
        )

        flow = payload.get("flow", "")
        reason = payload.get("reason", "LLM classification")

        if flow not in VALID_FLOWS:
            _log.warning(
                f"{tid} [ROUTER] LLM returned unknown flow={flow!r} — "
                f"falling back to heuristic"
            )
            flow = _heuristic_flow(text)
            reason = f"Heuristic fallback (LLM returned invalid flow: {flow!r})"

        _log.info(
            f"{tid} [ROUTER] Classification complete: flow={flow!r} "
            f"reason={reason!r} model={meta.get('model')!r} "
            f"tokens={meta.get('token_usage', {}).get('total_tokens', 0)}"
        )

        return {
            "flow": flow,
            "reason": reason,
            "model": meta["model"],
            "temperature": meta["temperature"],
            "token_usage": meta["token_usage"],
            "token_budget": budget,
        }

    except Exception as exc:
        flow = _heuristic_flow(text)
        _log.warning(
            f"{tid} [ROUTER] LLM classification FAILED — {exc!r}. "
            f"Using heuristic fallback: flow={flow!r}"
        )
        return {
            "flow": flow,
            "reason": "Heuristic fallback (LLM unavailable)",
            "model": "heuristic",
            "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }
