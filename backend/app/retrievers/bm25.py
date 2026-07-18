import re
from typing import Any

from rank_bm25 import BM25Okapi

from ..database import documents


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    docs = documents(project_key)
    if not docs:
        return []
    corpus = [_tokenize(f"{d['title']} {d['content']}") for d in docs]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(
        (
            {
                **doc,
                "bm25_score": round(float(score), 4),
                "score": round(float(score), 4),
            }
            for doc, score in zip(docs, scores)
        ),
        key=lambda x: x["score"],
        reverse=True,
    )
    return ranked[:limit]
