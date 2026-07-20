"""
Q&A agent — three read-only answer functions.

answer_from_rag:   BRD / knowledge documents → grounded answer
answer_from_jira:  Live Jira data → factual answer (uses NL→JQL)
answer_hybrid:     Both sources → gap analysis / implementation insight

None of these flows trigger human approval — they return immediately.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..prompts.qa_templates import (
    HYBRID_QA_SYSTEM,
    JIRA_QA_SYSTEM,
    NL_TO_JQL_SYSTEM,
    RAG_QA_SYSTEM,
    hybrid_qa_prompt,
    jira_qa_prompt,
    nl_to_jql_prompt,
    rag_qa_prompt,
)
from ..services.llm import invoke_json, invoke_llm
from ..services.tokens import token_budget

_EXPAND_SYSTEM = (
    "You are a search query expert. Given a question, generate 2 alternative phrasings "
    "that capture the same intent using different vocabulary. "
    "Return JSON with key: expansions (array of 2 strings). No explanations."
)

_log = logging.getLogger("agent")


def _tid(run) -> str:
    if run is not None:
        return f"[THREAD:{run.thread_id}]"
    return "[THREAD:no-run]"


def expand_query(question: str, _run=None) -> list[str]:
    """Return [original] + up to 2 LLM-generated alternate phrasings."""
    try:
        payload, _ = invoke_json(
            f"Question: {question}",
            task="extraction",
            max_tokens=200,
            system=_EXPAND_SYSTEM,
            _agent_tag="query_expand",
            _run=_run,
        )
        expansions = payload.get("expansions", [])
        if isinstance(expansions, list) and expansions:
            queries = [question] + [str(e) for e in expansions[:2] if str(e) != question]
            preview = question[:60]
            _log.debug(f"Query expansion: {len(queries)} variants for {preview!r}")
            return queries
    except Exception as exc:
        _log.debug(f"Query expansion failed ({exc}) — using original query only")
    return [question]


def _fallback_answer(question: str, source: str) -> dict[str, Any]:
    return {
        "answer": (
            f"I was unable to find a confident answer to your question using the available {source} data. "
            f"Please refine your query or check that the relevant documents are loaded."
        ),
        "sources_used": [],
        "data_points": [],
        "confidence": "low",
        "is_fallback": True,
    }


# ── RAG Q&A ───────────────────────────────────────────────────────────────────

def answer_from_rag(
    question: str,
    docs: list[dict[str, Any]],
    _run=None,
    project_key: str | None = None,
    history: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Answer a question from BRD / knowledge documents via hybrid search."""
    tid = _tid(_run)
    context = "\n\n".join(
        f"[{i+1}] {d['title']}\n{d.get('content', '')}" for i, d in enumerate(docs)
    )
    budget = token_budget("qa", question)  # falls back to {low:1200, med:2000, high:3000}; overridden by llm_params.max_tokens

    _log.info(
        f"{tid} [RAG_QA] Answering from BRD docs — "
        f"question_len={len(question)} docs={len(docs)} budget={budget}"
    )
    _log.debug(f"{tid} [RAG_QA] Question: {question!r}")
    _log.debug(f"{tid} [RAG_QA] Context ({len(docs)} docs):\n{context[:800]}")

    try:
        meta = invoke_llm(
            rag_qa_prompt(question, context, project_key=project_key, history=history),
            task="planning",
            max_tokens=budget,
            system=RAG_QA_SYSTEM,
            _agent_tag="rag_qa",
            _run=_run,
        )
        text = meta.pop("content", "").strip()
        if not text:
            _log.warning(f"{tid} [RAG_QA] LLM returned empty content — using fallback")
            return _fallback_answer(question, "BRD"), meta
        meta["token_budget"] = budget

        # Only surface sources the LLM actually cited — prevents phantom source refs
        available_titles = [d["title"] for d in docs if d.get("title")]
        sources_used = [t for t in available_titles if t.lower() in text.lower()]
        if not sources_used:
            sources_used = available_titles

        # Extract confidence level and explanation from the model's ## Confidence section.
        # Falls back to keyword heuristic only when the section is absent.
        confidence = "high"
        confidence_explanation = ""
        import re as _re
        conf_match = _re.search(
            r"##\s*Confidence\s*\n+.*?Level[:\s]+(\w+).*?Explanation[:\s]+([^\n]+)",
            text,
            _re.I | _re.S,
        )
        if conf_match:
            level_word = conf_match.group(1).strip().lower()
            confidence = level_word if level_word in ("high", "medium", "low") else "medium"
            confidence_explanation = conf_match.group(2).strip()
        else:
            low_phrases = (
                "cannot find", "not found", "no information", "not mentioned",
                "not covered", "unable to find", "does not specify", "not specified",
            )
            confidence = "low" if any(p in text.lower() for p in low_phrases) else "high"

        payload = {
            "answer": text,
            "sources_used": sources_used,
            "confidence": confidence,
            "confidence_explanation": confidence_explanation,
        }
        _log.info(f"{tid} [RAG_QA] Answer ready — chars={len(text)} sources={len(sources_used)} confidence={confidence}")
        return payload, meta
    except Exception as exc:
        _log.warning(f"{tid} [RAG_QA] FAILED — {exc!r}. Using fallback.")
        return _fallback_answer(question, "BRD"), {
            "model": "template", "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }


# ── NL → JQL ──────────────────────────────────────────────────────────────────

def nl_to_jql(question: str, project_key: str, _run=None) -> tuple[str, str]:
    """Convert a natural language question to a JQL query string."""
    tid = _tid(_run)
    budget = token_budget("extraction", question)
    _log.info(f"{tid} [NL_TO_JQL] Converting question to JQL — project={project_key!r}")
    _log.debug(f"{tid} [NL_TO_JQL] Question: {question!r}")

    try:
        payload, meta = invoke_json(
            nl_to_jql_prompt(question, project_key),
            task="extraction",
            max_tokens=budget,
            system=NL_TO_JQL_SYSTEM,
            _agent_tag="nl_to_jql",
            _run=_run,
        )
        jql = payload.get("jql", f"project = {project_key} ORDER BY updated DESC")
        explanation = payload.get("explanation", "")
        _log.info(f"{tid} [NL_TO_JQL] Generated JQL: {jql!r} — {explanation}")
        return jql, explanation, meta
    except Exception as exc:
        fallback_jql = f"project = {project_key} ORDER BY updated DESC"
        _log.warning(f"{tid} [NL_TO_JQL] Failed ({exc!r}) — using fallback JQL: {fallback_jql!r}")
        return fallback_jql, "Fallback: all recent issues", {}


# ── JIRA Q&A ──────────────────────────────────────────────────────────────────

def answer_from_jira(
    question: str,
    jira_docs: list[dict[str, Any]],
    _run=None,
    project_key: str | None = None,
    history: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Answer a question from live Jira metrics / search results."""
    tid = _tid(_run)
    # Format Jira data as readable context
    jira_context = "\n\n".join(
        f"[{d.get('title', f'Record {i+1}')}]\n{d.get('content', json.dumps(d, default=str))}"
        for i, d in enumerate(jira_docs)
    )
    budget = token_budget("structured", question)

    _log.info(
        f"{tid} [JIRA_QA] Answering from Jira data — "
        f"question_len={len(question)} records={len(jira_docs)} budget={budget}"
    )
    _log.debug(f"{tid} [JIRA_QA] Jira context preview:\n{jira_context[:800]}")

    try:
        payload, meta = invoke_json(
            jira_qa_prompt(question, jira_context, project_key=project_key, history=history),
            task="structured",
            max_tokens=budget,
            system=JIRA_QA_SYSTEM,
            _agent_tag="jira_qa",
            _run=_run,
        )
        if not payload or "answer" not in payload:
            _log.warning(f"{tid} [JIRA_QA] LLM returned no answer — using fallback")
            payload = _fallback_answer(question, "Jira")
        meta["token_budget"] = budget
        _log.info(
            f"{tid} [JIRA_QA] Answer ready — "
            f"confidence={payload.get('confidence','?')} "
            f"data_points={len(payload.get('data_points', []))}"
        )
        return payload, meta
    except Exception as exc:
        _log.warning(f"{tid} [JIRA_QA] FAILED — {exc!r}. Using fallback.")
        return _fallback_answer(question, "Jira"), {
            "model": "template", "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }


# ── HYBRID Q&A ────────────────────────────────────────────────────────────────

def answer_hybrid(
    question: str,
    brd_docs: list[dict[str, Any]],
    jira_docs: list[dict[str, Any]],
    _run=None,
    project_key: str | None = None,
    history: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cross-reference BRD docs and Jira data for implementation gap analysis."""
    tid = _tid(_run)
    brd_context = "\n\n".join(
        f"[BRD-{i+1}] {d['title']}\n{d.get('content', '')}" for i, d in enumerate(brd_docs)
    )
    jira_context = "\n\n".join(
        f"[JIRA-{i+1}] {d.get('title', f'Issue {i+1}')}\n{d.get('content', json.dumps(d, default=str))}"
        for i, d in enumerate(jira_docs)
    )
    budget = token_budget("creative", question)

    _log.info(
        f"{tid} [HYBRID_QA] Cross-referencing BRD + Jira — "
        f"brd_docs={len(brd_docs)} jira_records={len(jira_docs)} budget={budget}"
    )

    try:
        payload, meta = invoke_json(
            hybrid_qa_prompt(question, brd_context, jira_context, project_key=project_key, history=history),
            task="creative",
            max_tokens=budget,
            system=HYBRID_QA_SYSTEM,
            _agent_tag="hybrid_qa",
            _run=_run,
        )
        if not payload or "answer" not in payload:
            _log.warning(f"{tid} [HYBRID_QA] LLM returned no answer — using fallback")
            payload = _fallback_answer(question, "BRD + Jira")
        payload.setdefault("confidence_explanation", "")

        # Recompute counts from gaps array (single source of truth) and patch answer text.
        # The LLM's covered_count / summary line are often wrong; gaps[] is reliable.
        import re as _re
        gaps = payload.get("gaps", [])
        json_total = payload.get("total_count", 0)
        json_covered = max(0, json_total - len(gaps))
        pct = round(json_covered / json_total * 100) if json_total else 0
        payload["covered_count"] = json_covered
        payload["coverage_pct"] = pct

        # Patch the summary line in the markdown so it matches the corrected numbers
        answer_text = payload.get("answer", "")
        gaps_list = ", ".join(gaps) if gaps else "none"
        fixed_summary = f"{json_covered} of {json_total} requirements are covered ({pct}%). Missing: {gaps_list}."
        payload["answer"] = _re.sub(
            r"\d+ of \d+ requirements? are covered \(\d+%\).*?(?=\n|$)",
            fixed_summary,
            answer_text,
            count=1,
            flags=_re.DOTALL if "\n" not in answer_text[:200] else 0,
        )
        meta["token_budget"] = budget
        _log.info(
            f"{tid} [HYBRID_QA] Answer ready — "
            f"confidence={payload.get('confidence','?')} "
            f"gaps={len(payload.get('gaps', []))}"
        )
        return payload, meta
    except Exception as exc:
        _log.warning(f"{tid} [HYBRID_QA] FAILED — {exc!r}. Using fallback.")
        return _fallback_answer(question, "BRD + Jira"), {
            "model": "template", "temperature": 0.0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "token_budget": budget,
        }
