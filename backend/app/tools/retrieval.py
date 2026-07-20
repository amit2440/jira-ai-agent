from typing import Any

from langchain_core.tools import tool

from ..retrievers.bm25 import bm25_search
from ..retrievers.hybrid import hybrid_search
from ..retrievers.vector import vector_search


# Plain callables — used by workflow nodes directly
def bm25_search_tool(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    return bm25_search(query, limit=limit, project_key=project_key)


def vector_search_tool(query: str, limit: int = 5) -> list[dict[str, Any]]:
    return vector_search(query, limit=limit)


def hybrid_search_tool(query: str, limit: int = 3, project_key: str | None = None) -> list[dict[str, Any]]:
    return hybrid_search(query, limit=limit, project_key=project_key)


# @tool wrappers — used by the ReAct agent (StructuredTool, not directly callable)
@tool
def bm25_search_tool_react(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    """Keyword search (BM25) over the BRD knowledge base. Best for exact terms, acronyms, module codes, version numbers."""
    return bm25_search(query, limit=limit, project_key=project_key)


@tool
def vector_search_tool_react(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Semantic vector search over the BRD knowledge base. Best for concept / meaning-based queries."""
    return vector_search(query, limit=limit)


@tool
def hybrid_search_tool_react(query: str, limit: int = 3, project_key: str | None = None) -> list[dict[str, Any]]:
    """Hybrid BM25 + vector search with reranking over the BRD knowledge base. Use this for general BRD questions."""
    return hybrid_search(query, limit=limit, project_key=project_key)
