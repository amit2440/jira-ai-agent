import logging
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from ..config import DATA_DIR

_log = logging.getLogger("agent")

CHROMA_DB_DIR = DATA_DIR / "chroma_db"

_vectorstore = None


def _get_vectorstore():
    global _vectorstore
    if _vectorstore is None:
        if not CHROMA_DB_DIR.exists():
            _log.warning(f"Chroma DB not found at {CHROMA_DB_DIR}. Returning empty results.")
            return None
        embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-large-en-v1.5",
            encode_kwargs={"normalize_embeddings": True},
        )
        _vectorstore = Chroma(
            persist_directory=str(CHROMA_DB_DIR),
            embedding_function=embeddings
        )
    return _vectorstore


def has_project_vectors(project_key: str) -> bool:
    """True if Chroma has at least one chunk tagged with this project_key."""
    vs = _get_vectorstore()
    if not vs:
        return False
    try:
        results = vs.get(where={"project_key": project_key}, limit=1)
        return len(results.get("ids", [])) > 0
    except Exception:
        return False


def vector_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict[str, Any]]:
    vs = _get_vectorstore()
    if not vs:
        return []

    def _to_docs(results: list) -> list[dict[str, Any]]:
        ranked = []
        for doc, score in results:
            sim_score = 1.0 / (1.0 + float(score))
            ranked.append({
                "id": f"vec_{hash(doc.page_content)}",
                "title": doc.metadata.get("title", "Knowledge Document"),
                "content": doc.page_content,
                "vector_score": round(sim_score, 4),
                "score": round(sim_score, 4),
            })
        return sorted(ranked, key=lambda x: x["score"], reverse=True)

    # BGE-large asymmetric retrieval: prepend task instruction to query only (not to documents)
    retrieval_query = f"Represent this sentence for searching relevant passages: {query}"

    try:
        if project_key:
            # Filter to docs tagged with this project_key; fall back to unfiltered if none found.
            results = vs.similarity_search_with_score(
                retrieval_query, k=limit, filter={"project_key": project_key}
            )
            if not results:
                # Docs ingested before project_key tagging — return nothing rather than wrong-project data.
                _log.warning(
                    f"Vector search: no docs tagged project_key={project_key!r}. "
                    "Re-run ingest_brd.py --project-key to tag existing docs."
                )
                return []
            return _to_docs(results)
        else:
            return _to_docs(vs.similarity_search_with_score(retrieval_query, k=limit))
    except Exception as exc:
        _log.error(f"Vector search failed: {exc}")
        return []
