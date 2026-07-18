"""
Report agent — three-stage pipeline: plan → write → review.

Logging per stage:
  plan_report:   sections planned, doc count, budget
  write_report:  markdown length generated, model used
  review_report: review notes count, markdown delta
  WARNING: emitted whenever LLM fails and fallback is used
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..prompts.templates import (
    REPORT_PLANNER_SYSTEM,
    REPORT_REVIEWER_SYSTEM,
    REPORT_WRITER_SYSTEM,
    planner_prompt,
    reviewer_prompt,
    writer_prompt,
)
from ..services.llm import invoke_json
from ..services.tokens import token_budget
from ..tools.pii import redact

_log = logging.getLogger("agent")


def _tid(run) -> str:
    if run is not None:
        return f"[THREAD:{run.thread_id}]"
    return "[THREAD:no-run]"


def _fallback_report(text: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    context = "\n".join(f"- **{x['title']}**: {x.get('content', '')}" for x in refs)
    return {
        "title": "Project Status Report",
        "markdown": f"""# Project Status Report

## Executive Summary
{text}

## Jira Metrics Overview
{context}

## Defect Status
- Critical and high-priority defects are being actively tracked and resolved.
- Medium and low-priority defects are queued for the next sprint.

## Blockers & Risks
- Active blockers are being monitored and escalated as required.

## Next Steps
- Address and respond to all outstanding stakeholder comments.
- Verify acceptance of recently completed deliverables.
""",
    }


def plan_report(
    text: str,
    refs: list[dict[str, Any]],
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tid = _tid(_run)
    context = "\n".join(f"- {x['title']}: {x['content']}" for x in refs)
    budget = token_budget("planner", text)

    _log.info(
        f"{tid} [REPORT_PLANNER] Starting report planning — "
        f"text_len={len(text)} context_docs={len(refs)} token_budget={budget}"
    )
    _log.debug(
        f"{tid} [REPORT_PLANNER] Report scope request (first 500 chars): {text[:500]!r}"
    )
    _log.debug(
        f"{tid} [REPORT_PLANNER] Context doc titles: "
        + ", ".join(f"{x.get('title','?')!r}" for x in refs[:5])
    )

    try:
        _log.debug(f"{tid} [REPORT_PLANNER] Dispatching to LLM for report structure planning…")
        payload, meta = invoke_json(
            planner_prompt(text, context),
            task="planning",
            max_tokens=budget,
            system=REPORT_PLANNER_SYSTEM,
            _agent_tag="report_planner",
            _run=_run,
        )
        if not payload:
            _log.warning(
                f"{tid} [REPORT_PLANNER] LLM returned empty payload — using default plan structure"
            )
            payload = {
                "title": "Project Status Report",
                "sections": ["Executive Summary", "Jira Metrics", "Defect Status", "Blockers", "Next Steps"],
            }
        meta["token_budget"] = budget

        _log.info(
            f"{tid} [REPORT_PLANNER] Plan created — "
            f"title={payload.get('title','?')!r} "
            f"sections={payload.get('sections', [])}"
        )
        _log.debug(
            f"{tid} [REPORT_PLANNER:FULL_PLAN]\n"
            f"{'─' * 60}\n{json.dumps(payload, indent=2, default=str)}\n{'─' * 60}"
        )
        return payload, meta

    except Exception as exc:
        _log.warning(
            f"{tid} [REPORT_PLANNER] Planning FAILED — {exc!r}. "
            f"Using minimal default plan structure."
        )
        return {"title": "Project Status Report", "sections": ["Executive Summary", "Jira Metrics"]}, {
            "model": "template",
            "temperature": 0.7,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }


def write_report(
    text: str,
    plan: dict[str, Any],
    refs: list[dict[str, Any]],
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tid = _tid(_run)
    safe_text = redact(text)
    context = "\n".join(f"- {x['title']}: {x['content']}" for x in refs)
    budget = token_budget("writer", text)

    _log.info(
        f"{tid} [REPORT_WRITER] Starting report writing — "
        f"plan_title={plan.get('title','?')!r} "
        f"sections={plan.get('sections',[])} "
        f"context_docs={len(refs)} token_budget={budget}"
    )
    _log.debug(
        f"{tid} [REPORT_WRITER] Using plan: {json.dumps(plan, default=str)}"
    )

    try:
        _log.debug(f"{tid} [REPORT_WRITER] Dispatching to LLM for report writing…")
        payload, meta = invoke_json(
            writer_prompt(safe_text, plan, context),
            task="creative",
            max_tokens=budget,
            system=REPORT_WRITER_SYSTEM,
            _agent_tag="report_writer",
            _run=_run,
        )
        if not payload or "markdown" not in payload:
            _log.warning(
                f"{tid} [REPORT_WRITER] LLM returned invalid payload (missing 'markdown' key) — "
                f"using fallback report template"
            )
            payload = _fallback_report(safe_text, refs)
        else:
            payload.setdefault("title", plan.get("title", "Project Status Report"))

        meta["token_budget"] = budget
        md_len = len(payload.get("markdown", ""))
        _log.info(
            f"{tid} [REPORT_WRITER] Report draft written — "
            f"title={payload.get('title','?')!r} "
            f"markdown_chars={md_len} sections_approx={payload.get('markdown','').count('##')}"
        )
        _log.debug(
            f"{tid} [REPORT_WRITER:MARKDOWN_PREVIEW]\n"
            f"{'─' * 60}\n{payload.get('markdown','')[:1500]}\n{'─' * 60}"
        )
        return payload, meta

    except Exception as exc:
        _log.warning(
            f"{tid} [REPORT_WRITER] Writing FAILED — {exc!r}. "
            f"Using fallback report template."
        )
        return _fallback_report(safe_text, refs), {
            "model": "template",
            "temperature": 0.8,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }


def review_report(
    report: dict[str, Any],
    _run=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tid = _tid(_run)
    md_input = report.get("markdown", "")
    budget = token_budget("reviewer", md_input)

    _log.info(
        f"{tid} [REPORT_REVIEWER] Starting report review — "
        f"markdown_chars_in={len(md_input)} token_budget={budget}"
    )
    _log.debug(
        f"{tid} [REPORT_REVIEWER] Markdown to review (first 800 chars):\n{md_input[:800]}"
    )

    try:
        _log.debug(f"{tid} [REPORT_REVIEWER] Dispatching to LLM for quality review…")
        payload, meta = invoke_json(
            reviewer_prompt(md_input),
            task="extraction",
            max_tokens=budget,
            system=REPORT_REVIEWER_SYSTEM,
            _agent_tag="report_reviewer",
            _run=_run,
        )
        if payload and "markdown" in payload:
            md_out = payload["markdown"]
            notes = payload.get("notes", [])
            chars_delta = len(md_out) - len(md_input)
            report = {**report, "markdown": md_out, "review_notes": notes}
            _log.info(
                f"{tid} [REPORT_REVIEWER] Review complete — "
                f"markdown_chars_out={len(md_out)} delta={chars_delta:+d} "
                f"review_notes_count={len(notes)}"
            )
            if notes:
                _log.debug(
                    f"{tid} [REPORT_REVIEWER] Review notes: {notes}"
                )
        else:
            _log.warning(
                f"{tid} [REPORT_REVIEWER] Reviewer returned no markdown — keeping original draft"
            )

        meta["token_budget"] = budget
        return report, meta

    except Exception as exc:
        _log.warning(
            f"{tid} [REPORT_REVIEWER] Review FAILED — {exc!r}. "
            f"Returning original unreviewed draft."
        )
        return report, {
            "model": "template",
            "temperature": 0.1,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }
