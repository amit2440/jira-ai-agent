import re
from typing import Any

from ..database import fts_search


def _escape_fts(query: str) -> str:
    """Build a safe FTS5 MATCH expression from a natural language query."""
    cleaned = re.sub(r'[^\w\s]', ' ', query.lower())
    tokens = [t for t in cleaned.split() if len(t) > 1]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"*' for t in tokens)


def bm25_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    fts_query = _escape_fts(query)
    try:
        rows = fts_search(fts_query, limit=limit, project_key=project_key)
    except Exception:
        # FTS5 query failed (e.g. empty table) — return empty
        return []
    return [
        {**row, "bm25_score": round(-float(row.get("bm25_score", 0)), 4),
         "score": round(-float(row.get("bm25_score", 0)), 4)}
        for row in rows
    ]
