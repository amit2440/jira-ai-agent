from typing import Any

from ..retrievers.bm25 import bm25_search
from ..retrievers.hybrid import hybrid_search
from ..retrievers.vector import vector_search


def bm25_search_tool(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    return bm25_search(query, limit=limit, project_key=project_key)


def vector_search_tool(query: str, limit: int = 5) -> list[dict[str, Any]]:
    return vector_search(query, limit=limit)


def hybrid_search_tool(query: str, limit: int = 3, project_key: str | None = None) -> list[dict[str, Any]]:
    return hybrid_search(query, limit=limit, project_key=project_key)
