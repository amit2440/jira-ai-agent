"""
Ticket agent — enhances requirements and generates structured Jira ticket drafts.

Logging:
  - Pre-call: text length, context doc count, token budget, model, temperature
  - Post-call: ticket summary, priority, issue_type, AC count, labels
  - DEBUG: full generated ticket JSON
  - WARNING: when LLM fails and fallback template is used
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..prompts.templates import (
    CONTRADICTION_SYSTEM,
    TICKET_SYSTEM,
    contradiction_prompt,
    ticket_prompt,
)
from ..services.llm import invoke_json
from ..services.tokens import token_budget
from ..tools.pii import redact

_log = logging.getLogger("agent")


def _tid(run) -> str:
    if run is not None:
        return f"[THREAD:{run.thread_id}]"
    return "[THREAD:no-run]"


def _fallback_ticket(text: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = text.strip().split(".")[0][:110]
    return {
        "summary": summary,
        "description": (
            f"## Business Requirement\n{text}\n\n## Reference Context\n"
            + "\n".join(f"- {x['title']}" for x in refs)
        ),
        "priority": "Medium",
        "issue_type": "Story",
        "acceptance_criteria": [
            "Given an eligible user, when they complete the requested action, then the outcome is persisted.",
            "Given invalid input, when submitted, then a clear actionable error message is displayed.",
            "Given deployment, when monitored, then no PII appears in application logs.",
        ],
        "labels": ["ai-generated", "requirements"],
    }


def generate_ticket(
    text: str,
    refs: list[dict[str, Any]],
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tid = _tid(_run)
    safe_text = redact(text)
    context = "\n".join(f"- {x['title']}: {x['content']}" for x in refs)
    budget = token_budget("ticket", text)

    _log.info(
        f"{tid} [TICKET_GENERATOR] Starting ticket generation — "
        f"text_len={len(safe_text)} context_docs={len(refs)} token_budget={budget}"
    )
    _log.debug(
        f"{tid} [TICKET_GENERATOR] Requirement text (redacted, first 500 chars): "
        f"{safe_text[:500]!r}"
    )
    _log.debug(
        f"{tid} [TICKET_GENERATOR] Context references ({len(refs)} docs): "
        + ", ".join(f"{x.get('title','?')!r}" for x in refs[:5])
    )

    try:
        _log.debug(f"{tid} [TICKET_GENERATOR] Dispatching to LLM for ticket generation…")
        payload, meta = invoke_json(
            ticket_prompt(safe_text, context),
            task="structured",
            max_tokens=budget,
            system=TICKET_SYSTEM,
            _agent_tag="ticket_generator",
            _run=_run,
        )

        if not payload:
            _log.warning(
                f"{tid} [TICKET_GENERATOR] LLM returned empty payload — "
                f"using fallback ticket template"
            )
            payload = _fallback_ticket(safe_text, refs)
        else:
            payload.setdefault("priority", "Medium")
            payload.setdefault("issue_type", "Story")
            payload.setdefault("labels", ["ai-generated"])
            payload.setdefault("acceptance_criteria", [])
            payload.setdefault("confidence", "medium")

        meta["token_budget"] = budget

        _log.info(
            f"{tid} [TICKET_GENERATOR] Ticket generated — "
            f"summary={payload.get('summary','')[:80]!r} "
            f"priority={payload.get('priority')} "
            f"issue_type={payload.get('issue_type')} "
            f"ac_count={len(payload.get('acceptance_criteria', []))} "
            f"labels={payload.get('labels', [])}"
        )
        _log.debug(
            f"{tid} [TICKET_GENERATOR:FULL_TICKET]\n"
            f"{'─' * 60}\n{json.dumps(payload, indent=2, default=str)[:2000]}\n{'─' * 60}"
        )

        return payload, meta

    except Exception as exc:
        _log.warning(
            f"{tid} [TICKET_GENERATOR] Generation FAILED — {exc!r}. "
            f"Using fallback ticket template."
        )
        return _fallback_ticket(safe_text, refs), {
            "model": "template",
            "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }


def detect_contradictions(
    text: str,
    refs: list[dict[str, Any]],
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Compare user requirement against BRD sections to detect contradictions,
    ambiguities, and wrong personas before ticket generation.

    Returns (analysis_dict, meta) where analysis_dict contains:
      contradictions, ambiguities, clarification_needed, grounded_requirement
    """
    tid = _tid(_run)
    safe_text = redact(text)
    context = "\n".join(f"- {x['title']}: {x['content'][:400]}" for x in refs)

    _log.info(
        f"{tid} [CONTRADICTION_DETECTOR] Checking requirement against "
        f"{len(refs)} BRD sections"
    )

    try:
        payload, meta = invoke_json(
            contradiction_prompt(safe_text, context),
            task="structured",
            max_tokens=800,
            system=CONTRADICTION_SYSTEM,
            _agent_tag="contradiction_detector",
            _run=_run,
        )
        payload.setdefault("contradictions", [])
        payload.setdefault("ambiguities", [])
        payload.setdefault("clarification_needed", False)
        payload.setdefault("grounded_requirement", safe_text)

        if payload["contradictions"]:
            _log.info(
                f"{tid} [CONTRADICTION_DETECTOR] Found {len(payload['contradictions'])} "
                f"contradiction(s): "
                + ", ".join(c.get("term", "?") for c in payload["contradictions"])
            )
        if payload["ambiguities"]:
            _log.info(
                f"{tid} [CONTRADICTION_DETECTOR] Found {len(payload['ambiguities'])} "
                f"ambiguit(ies)"
            )

        return payload, meta

    except Exception as exc:
        _log.warning(f"{tid} [CONTRADICTION_DETECTOR] Failed: {exc!r} — skipping check")
        return {
            "contradictions": [],
            "ambiguities": [],
            "clarification_needed": False,
            "grounded_requirement": redact(text),
        }, {"model": "fallback", "token_usage": {"total_tokens": 0}}


def enhance_requirement(
    text: str,
    refs: list[dict[str, Any]] | None = None,
    _run=None,
) -> tuple[str, dict[str, Any]]:
    """
    PII-redact and return the requirement. If BRD refs are provided and a
    grounded_requirement was produced by detect_contradictions, callers should
    pass that directly; this function handles the base case.
    """
    tid = _tid(_run)
    budget = token_budget("enhancement", text)
    safe_text = redact(text)

    _log.info(
        f"{tid} [REQUIREMENT_ENHANCER] PII redaction complete — "
        f"original_len={len(text)} redacted_len={len(safe_text)} "
        f"chars_removed={len(text) - len(safe_text)}"
    )

    return safe_text, {
        "model": "normalizer",
        "temperature": 0.7,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "token_budget": budget,
    }
