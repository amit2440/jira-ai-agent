"""
ReAct retrieval layer for Q&A flows (rag_qa, jira_qa, hybrid_qa).

The LLM sees the question + available tools and picks which to call.
Tools execute once; raw docs are returned split by source (BRD vs Jira).
Synthesis is handled by the original answer_from_* functions in agents/qa.py
so prompt quality and confidence scoring are unchanged.

Entry point: run_retrieval_react(question, project_key, flow_hint, _run)
             -> (brd_docs, jira_docs, meta)
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import GROQ_API_KEY, GROQ_MODEL, TEMPERATURE, groq_enabled
from ..tools.jira import jira_project_health, jira_project_health_react, jira_search, jira_search_react
from ..tools.retrieval import (
    bm25_search_tool,
    bm25_search_tool_react,
    hybrid_search_tool,
    hybrid_search_tool_react,
    vector_search_tool,
    vector_search_tool_react,
)

_log = logging.getLogger("agent")

_QA_TOOLS = [
    hybrid_search_tool_react,
    bm25_search_tool_react,
    vector_search_tool_react,
    jira_search_react,
    jira_project_health_react,
]

# Map @tool name → plain callable for direct execution after LLM selection
_TOOL_EXECUTORS: dict[str, Any] = {
    "hybrid_search_tool_react": hybrid_search_tool,
    "bm25_search_tool_react": bm25_search_tool,
    "vector_search_tool_react": vector_search_tool,
    "jira_search_react": jira_search,
    "jira_project_health_react": jira_project_health,
}

_BRD_TOOLS = {"hybrid_search_tool_react", "bm25_search_tool_react", "vector_search_tool_react"}
_JIRA_TOOLS = {"jira_search_react", "jira_project_health_react"}

_RETRIEVAL_SYSTEM = (
    "You are a retrieval planner. Given a question and available tools, "
    "select the most appropriate tool(s) to fetch relevant context. "
    "For BRD/requirements questions use hybrid_search_tool_react. "
    "For Jira/project status questions use jira_search_react or jira_project_health_react. "
    "For gap analysis use both BRD and Jira tools. "
    "Call the tools now — do not answer the question yourself."
)


def _get_llm():
    if not groq_enabled():
        return None
    from langchain_groq import ChatGroq
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
        temperature=TEMPERATURE.get("extraction", 0.0),
        max_tokens=500,
    ).bind_tools(_QA_TOOLS)


def _normalize_jira_result(result: Any) -> list[dict[str, Any]]:
    """Convert jira_search / jira_project_health output to doc list."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "issues" in result:
        return [
            {
                "title": f"{i.get('key', '')}: {i.get('summary', '')}",
                "content": f"Key: {i.get('key')} | Status: {i.get('status', 'Unknown')} | Summary: {i.get('summary', '')}",
                "source": "jira",
            }
            for i in result["issues"]
        ]
    return []


def run_retrieval_react(
    question: str,
    project_key: str,
    flow_hint: str = "rag_qa",
    _run=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """
    Let the LLM pick retrieval tools, execute them, return (brd_docs, jira_docs, meta).
    Falls back to deterministic tool selection when Groq is unavailable.
    """
    meta = {"model": GROQ_MODEL, "token_usage": {"total_tokens": 0}}

    llm = _get_llm()

    if llm is None:
        # Demo mode — fall back to deterministic retrieval matching old behaviour
        return _fallback_retrieval(question, project_key, flow_hint)

    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        response = llm.invoke([
            SystemMessage(content=_RETRIEVAL_SYSTEM),
            HumanMessage(content=f"Project: {project_key}\nFlow: {flow_hint}\nQuestion: {question}"),
        ])

        usage = getattr(response, "response_metadata", {}).get("token_usage", {})
        meta["token_usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        tool_calls = getattr(response, "tool_calls", []) or []
        if not tool_calls:
            _log.warning("ReAct retrieval: LLM made no tool calls — falling back to deterministic")
            return _fallback_retrieval(question, project_key, flow_hint)

        brd_docs: list[dict[str, Any]] = []
        jira_docs: list[dict[str, Any]] = []

        for call in tool_calls:
            name = call["name"]
            args = call.get("args", {})
            executor = _TOOL_EXECUTORS.get(name)
            if executor is None:
                _log.warning(f"ReAct retrieval: unknown tool {name!r} — skipping")
                continue

            # Inject project_key if the tool accepts it and caller didn't set one
            if "project_key" in args or name in _JIRA_TOOLS:
                args.setdefault("project_key", project_key)

            try:
                result = executor(**args)
            except Exception as exc:
                _log.warning(f"ReAct retrieval: tool {name!r} failed — {exc}")
                continue

            if name in _BRD_TOOLS:
                if isinstance(result, list):
                    brd_docs.extend(result)
            elif name in _JIRA_TOOLS:
                jira_docs.extend(_normalize_jira_result(result))

        _log.info(
            f"ReAct retrieval: brd_docs={len(brd_docs)} jira_docs={len(jira_docs)} "
            f"tools_called={[c['name'] for c in tool_calls]}"
        )
        return brd_docs, jira_docs, meta

    except Exception as exc:
        _log.error(f"ReAct retrieval failed: {exc}", exc_info=True)
        return _fallback_retrieval(question, project_key, flow_hint)


def _fallback_retrieval(
    question: str,
    project_key: str,
    flow_hint: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Deterministic fallback — mirrors the old hardcoded node behaviour."""
    meta = {"model": "demo-template", "token_usage": {"total_tokens": 0}}
    brd_docs: list[dict[str, Any]] = []
    jira_docs: list[dict[str, Any]] = []

    if flow_hint in ("rag_qa", "hybrid_qa"):
        brd_docs = hybrid_search_tool(question, limit=5, project_key=project_key)

    if flow_hint in ("jira_qa", "hybrid_qa"):
        raw = jira_search(f"project = {project_key} ORDER BY updated DESC", max_results=10)
        jira_docs = _normalize_jira_result(raw) or jira_project_health(project_key)

    return brd_docs, jira_docs, meta
