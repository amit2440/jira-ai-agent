"""
ReAct agent for Q&A flows (rag_qa, jira_qa, hybrid_qa).

Replaces the three hardcoded node chains with a single LangGraph ReAct loop:
  LLM decides which tools to call → ToolNode executes → LLM synthesises answer.

Tools available to the agent:
  hybrid_search_tool   — BRD hybrid search (BM25 + vector, reranked)
  bm25_search_tool     — BRD keyword search
  vector_search_tool   — BRD semantic search
  jira_search          — Execute JQL against Jira
  jira_project_health  — Fetch Jira project health summary

Entry point: run_qa_react(question, project_key, flow_hint, run) -> (answer_payload, docs, meta)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import Annotated, TypedDict

from ..config import GROQ_API_KEY, GROQ_MODEL, TEMPERATURE, groq_enabled
from ..tools.jira import jira_project_health_react, jira_search_react
from ..tools.retrieval import bm25_search_tool_react, hybrid_search_tool_react, vector_search_tool_react

_log = logging.getLogger("agent")

_QA_TOOLS = [
    hybrid_search_tool_react,
    bm25_search_tool_react,
    vector_search_tool_react,
    jira_search_react,
    jira_project_health_react,
]

_SYSTEM_PROMPT = """You are an AI assistant for a software project. You have access to:
- BRD (Business Requirements Document) search tools for requirements/documentation questions
- Jira tools for project status, tickets, and health metrics

Use the most appropriate tool(s) for the question. For BRD questions, prefer hybrid_search_tool.
For Jira questions, prefer jira_search or jira_project_health. For gap analysis, use both.

After gathering context, synthesise a clear, grounded answer. Return your final answer as JSON:
{{
  "answer": "string — main answer text",
  "confidence": "high|medium|low",
  "sources_used": ["list of document titles used"],
  "gaps": []
}}
For hybrid gap analysis, populate "gaps" with a list of missing requirement strings.
"""


class _AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    project_key: str


def _build_react_graph():
    if not groq_enabled():
        return None

    from langchain_groq import ChatGroq

    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
        temperature=TEMPERATURE.get("qa", 0.1),
        max_tokens=2000,
    ).bind_tools(_QA_TOOLS)

    def call_llm(state: _AgentState) -> dict:
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: _AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(_QA_TOOLS)

    graph = StateGraph(_AgentState)
    graph.add_node("llm", call_llm)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "llm")
    return graph.compile()


_REACT_GRAPH = None


def _get_graph():
    global _REACT_GRAPH
    if _REACT_GRAPH is None:
        _REACT_GRAPH = _build_react_graph()
    return _REACT_GRAPH


def _extract_tool_docs(messages: list) -> list[dict[str, Any]]:
    """Pull retrieved documents out of ToolMessage results."""
    docs: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and ("title" in item or "content" in item):
                        docs.append(item)
            elif isinstance(content, dict) and "issues" in content:
                issues = content["issues"]
                for issue in issues:
                    docs.append({
                        "title": f"{issue.get('key', '')}: {issue.get('summary', '')}",
                        "content": f"Key: {issue.get('key')} | Status: {issue.get('status', '')} | Summary: {issue.get('summary', '')}",
                        "source": "jira",
                    })
        except Exception:
            pass
    return docs


def _parse_answer(messages: list) -> dict[str, Any]:
    """Extract the JSON answer payload from the last AI message."""
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = str(msg.content)
        if not content.strip():
            continue
        import re
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"answer": content, "confidence": "medium", "sources_used": [], "gaps": []}
    return {"answer": "No answer generated.", "confidence": "low", "sources_used": [], "gaps": []}


def run_qa_react(
    question: str,
    project_key: str,
    flow_hint: str = "rag_qa",
    _run=None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """
    Run the ReAct Q&A agent. Returns (answer_payload, retrieved_docs, meta).

    Falls back to a demo response when Groq is not configured.
    """
    graph = _get_graph()

    if graph is None:
        # Demo mode fallback
        return (
            {"answer": "Demo mode — configure GROQ_API_KEY to enable live answers.",
             "confidence": "low", "sources_used": [], "gaps": []},
            [],
            {"model": "demo-template", "token_usage": {"total_tokens": 0}},
        )

    flow_context = {
        "rag_qa": "Focus on BRD knowledge base documents.",
        "jira_qa": "Focus on Jira project data and ticket status.",
        "hybrid_qa": "Cross-reference BRD requirements against Jira coverage to identify gaps.",
    }.get(flow_hint, "")

    system_msg = SystemMessage(content=_SYSTEM_PROMPT)
    human_msg = HumanMessage(
        content=f"Project: {project_key}\n{flow_context}\n\nQuestion: {question}"
    )

    try:
        result = graph.invoke(
            {"messages": [system_msg, human_msg], "project_key": project_key},
        )
        messages = result["messages"]
        answer = _parse_answer(messages)
        docs = _extract_tool_docs(messages)

        # Count tokens from tool call round-trips (approximate)
        meta = {
            "model": GROQ_MODEL,
            "token_usage": {"total_tokens": 0},
        }
        return answer, docs, meta

    except Exception as exc:
        _log.error(f"ReAct agent failed: {exc}", exc_info=True)
        return (
            {"answer": f"Agent error: {exc}", "confidence": "low", "sources_used": [], "gaps": []},
            [],
            {"model": GROQ_MODEL, "token_usage": {"total_tokens": 0}},
        )
