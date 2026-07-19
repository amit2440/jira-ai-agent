#!/usr/bin/env python3
"""
Before/after retrieval comparison.

Run from backend/ with venv active:
    python scripts/test_retrieval.py

Tests three sample queries and prints ranked results from:
  1. BM25 only (baseline)
  2. Vector only
  3. Hybrid RRF (old: no reranker)
  4. Hybrid + Cross-encoder reranker (new)
  5. Hybrid + Reranker + Query expansion (new, full stack)

Results are printed side-by-side so you can see improvement.
"""
import sys
import textwrap
from pathlib import Path

# Add backend/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_QUERIES = [
    "user login authentication requirements",
    "document upload file size limits",
    "email notification approval workflow",
]


def fmt(docs, label, width=60):
    print(f"\n  {'─' * width}")
    print(f"  {label}")
    print(f"  {'─' * width}")
    if not docs:
        print("  (no results)")
        return
    for i, d in enumerate(docs[:5], 1):
        score     = d.get("rerank_score") or d.get("score") or 0
        bm25      = d.get("bm25_score")
        vec       = d.get("vector_score")
        score_str = f"rerank={score:.3f}" if d.get("rerank_score") else f"score={score:.3f}"
        sub       = f"  bm25={bm25:.3f}" if bm25 else ""
        sub      += f"  vec={vec:.3f}" if vec else ""
        title     = textwrap.shorten(d.get("title", "?"), width=50)
        print(f"  {i}. {title}")
        print(f"     {score_str}{sub}")


def main():
    print("Loading retrievers…")
    from app.retrievers.bm25 import bm25_search
    from app.retrievers.hybrid import hybrid_search, _get_reranker
    from app.retrievers.vector import vector_search
    from app.agents.qa import expand_query

    reranker_available = _get_reranker() is not None
    print(f"Reranker available: {reranker_available}")
    print(f"Running {len(TEST_QUERIES)} test queries\n")

    for query in TEST_QUERIES:
        print(f"\n{'═' * 70}")
        print(f"  QUERY: {query!r}")
        print(f"{'═' * 70}")

        bm25_results   = bm25_search(query, limit=5)
        vector_results = vector_search(query, limit=5)
        hybrid_results = hybrid_search(query, limit=5)

        fmt(bm25_results,   "1. BM25 only (baseline)")
        fmt(vector_results, "2. Vector only (BGE-large)")
        fmt(hybrid_results, f"3. Hybrid RRF + Reranker ({'✓ reranked' if reranker_available else '✗ reranker unavailable'})")

        # Query expansion
        expanded = expand_query(query)
        if len(expanded) > 1:
            seen: dict[str, dict] = {}
            for q in expanded:
                for doc in hybrid_search(q, limit=5):
                    key = doc.get("id") or doc.get("title")
                    if key not in seen or doc.get("score", 0) > seen[key].get("score", 0):
                        seen[key] = doc
            expanded_results = sorted(
                seen.values(),
                key=lambda d: d.get("rerank_score", d.get("score", 0)),
                reverse=True,
            )[:5]
            fmt(expanded_results, f"4. Hybrid + Reranker + Query Expansion ({len(expanded)} variants)")
        else:
            print("\n  4. Query expansion skipped (LLM not available or same query returned)")

    print(f"\n{'═' * 70}")
    print("  NOTES:")
    print("  - BGE-large requires ChromaDB to be rebuilt with: python scripts/ingest_brd.py --project-key EOMS")
    print("  - Cross-encoder reranker downloads cross-encoder/ms-marco-MiniLM-L-6-v2 on first run (~85MB)")
    print("  - Query expansion requires GROQ_API_KEY to be set")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()
