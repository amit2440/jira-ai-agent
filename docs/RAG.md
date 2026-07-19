# RAG Design

## Overview

Hybrid RAG: two independent retrievers run in parallel, scores fused via Reciprocal Rank Fusion (RRF), then a cross-encoder reranker reorders the fused list. Query expansion generates alternate phrasings to increase vocabulary coverage.

## Pipeline

```
User query
    │
    ▼
expand_query()  ──  LLM generates 2 alternate phrasings
    │               [original, alt1, alt2]
    ▼
For each query variant:
    ├── BM25 search (SQLite knowledge table)
    └── Vector search (ChromaDB)
    │
    ▼
Deduplicate by best score across variants
    │
    ▼
RRF fusion  ──  rrf_score = 1/(k + rank_bm25) + 1/(k + rank_vector)  [k=60]
    │
    ▼
Cross-encoder reranker  ──  (query, doc_content[:512]) → rerank_score
    │
    ▼
Sort by rerank_score  ──  return top-k
```

## Components

### BM25 — `retrievers/bm25.py`
- Library: `rank-bm25`
- Corpus: SQLite `knowledge` table (synced during ingestion via `ingest_brd.py`)
- Tokenization: whitespace split, lowercased
- Fetches `max(limit*4, 20)` candidates before fusion to give reranker wider candidate pool
- Each doc gets `bm25_score` in result metadata

### Vector Search — `retrievers/vector.py`
- Model: `BAAI/bge-large-en-v1.5` (1024-dim, asymmetric retrieval)
- Store: ChromaDB (`backend/chroma_db/`)
- Ingestion: `backend/scripts/ingest_brd.py` — chunk size 800, overlap 150
- BGE query prefix applied: `"Represent this sentence for searching relevant passages: {query}"`
- `encode_kwargs={"normalize_embeddings": True}` for cosine similarity
- Each doc gets `vector_score` in result metadata

> **Important:** BGE-large has different embedding dimensions (1024) vs the previous MiniLM (384). Existing Chroma index must be rebuilt after switching models:
> ```bash
> python backend/scripts/ingest_brd.py --project-key EOMS
> ```

### RRF Fusion — `retrievers/hybrid.py`
Combines BM25 and vector result lists without score normalization:
```python
rrf_score(doc) = 1/(k + rank_bm25) + 1/(k + rank_vector)
# k=60 dampens the effect of high ranks; docs ranked well in both lists score highest
```
Result metadata includes `bm25_score`, `vector_score`, and `rrf_score`.

### Cross-Encoder Reranker — `retrievers/hybrid.py`
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Lazy-loaded on first call; `_reranker = False` sentinel prevents retry after load failure
- Scores `(query, content[:512])` pairs → `rerank_score` ∈ [-10, 10]
- Falls back gracefully (uses rrf_score ordering) if model unavailable
- Final sort is by `rerank_score` descending

### Query Expansion — `agents/qa.py`
- LLM generates 2 alternate phrasings for the user's question
- All 3 queries searched independently through both retrievers
- Results deduplicated by content hash; best score per document kept
- Increases vocabulary coverage: handles synonym mismatches between user query and indexed docs
- Falls back to original query only if LLM expansion fails

## Data Flow (rag_qa flow)

```
user: "What does the BRD say about employee document upload limits?"
    │
    expand_query → ["What does the BRD say about employee document upload limits?",
                    "Document upload size restrictions for employee portal",
                    "File upload constraints in EOMS specification"]
    │
    Each variant → BM25 + Vector → dedup (keep best score per doc)
    │
    RRF fusion → ranked list
    │
    Cross-encoder → rerank_score for each → sort
    │
    Top 5 docs sent to LLM as context
    │
    LLM answers citing source titles
```

## Corpora Alignment

BM25 reads from SQLite `knowledge` table. Vector search reads from Chroma. `ingest_brd.py` writes to **both** (`_sync_to_sqlite`) to keep them in sync.

Documents added via `/api/knowledge` go to SQLite only (BM25-searchable). To add them to Chroma for vector search, run `ingest_brd.py` with a merged PDF or extend the script to embed from the `knowledge` table.

## Observability

Each retrieved document in events carries:
- `title`, `content` (truncated)
- `bm25_score`, `vector_score`, `rrf_score`, `rerank_score`
- `project_key`

Event detail includes `query_variants` count when query expansion is active.
