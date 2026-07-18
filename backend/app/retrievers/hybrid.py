from typing import Any

from .bm25 import bm25_search
from .vector import vector_search


def hybrid_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    bm25_docs = bm25_search(query, limit=limit * 2, project_key=project_key)
    vector_docs = vector_search(query, limit=limit * 2, project_key=project_key)
    
    # Reciprocal Rank Fusion (RRF)
    k = 60
    rrf_scores: dict[str, float] = {}
    merged: dict[str, dict[str, Any]] = {}
    
    for rank, doc in enumerate(bm25_docs):
        doc_id = doc.get("id") or doc.get("title")
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in merged:
            merged[doc_id] = doc
            
    for rank, doc in enumerate(vector_docs):
        doc_id = doc.get("id") or doc.get("title")
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in merged:
            merged[doc_id] = doc
            
    ranked = []
    for doc_id, doc in merged.items():
        score = round(rrf_scores[doc_id], 4)
        ranked.append({**doc, "score": score})
        
    return sorted(ranked, key=lambda x: x["score"], reverse=True)[:limit]
