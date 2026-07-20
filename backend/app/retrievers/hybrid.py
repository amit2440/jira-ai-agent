import logging
from typing import Any

from .bm25 import bm25_search
from .vector import vector_search

_log = logging.getLogger("agent")

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            _log.info("Reranker loaded: cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as exc:
            _log.warning(f"Reranker unavailable ({exc}) — skipping rerank step")
            _reranker = False  # sentinel: don't retry
    return _reranker if _reranker is not False else None


def hybrid_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    # Fetch more candidates than needed — reranker will cut to `limit`
    fetch_k = max(limit * 4, 20)
    bm25_docs   = bm25_search(query, limit=fetch_k, project_key=project_key)
    vector_docs = vector_search(query, limit=fetch_k, project_key=project_key)

    # ── Reciprocal Rank Fusion ────────────────────────────────────────────────
    k = 60
    rrf_scores: dict[str, float] = {}
    merged: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(bm25_docs):
        doc_id = doc.get("title") or doc.get("id")
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in merged:
            merged[doc_id] = {**doc, "bm25_rank": rank}

    for rank, doc in enumerate(vector_docs):
        doc_id = doc.get("title") or doc.get("id")
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        if doc_id not in merged:
            merged[doc_id] = {**doc, "vector_rank": rank}
        else:
            merged[doc_id]["vector_rank"] = rank

    rrf_ranked = sorted(
        [{**doc, "score": round(rrf_scores[doc.get("title") or doc.get("id")], 4)} for doc in merged.values()],
        key=lambda x: x["score"],
        reverse=True,
    )

    # ── Cross-encoder rerank ──────────────────────────────────────────────────
    reranker = _get_reranker()
    if reranker and rrf_ranked:
        try:
            pairs = [(query, d.get("content", "")[:512]) for d in rrf_ranked]
            ce_scores = reranker.predict(pairs)
            for doc, ce_score in zip(rrf_ranked, ce_scores):
                doc["rerank_score"] = round(float(ce_score), 4)
            rrf_ranked = sorted(rrf_ranked, key=lambda x: x.get("rerank_score", 0), reverse=True)
            _log.debug(f"Reranked {len(rrf_ranked)} docs; top rerank_score={rrf_ranked[0].get('rerank_score'):.3f}")
        except Exception as exc:
            _log.warning(f"Reranker predict failed ({exc}) — using RRF order")

    return rrf_ranked[:limit]
