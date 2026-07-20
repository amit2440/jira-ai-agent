# RAG Design

## Overview

Hybrid RAG: two independent retrievers run in parallel, scores fused via Reciprocal Rank Fusion (RRF), then a cross-encoder reranker reorders the fused list. Query expansion generates alternate phrasings to increase vocabulary coverage. A ReAct tool-selection layer (`graph/react_agent.py`) sits in front of retrieval for the three Q&A flows — the LLM picks which retrieval tool(s) to call rather than the graph hardcoding one path per flow.

## Pipeline

```
User query
    │
    ▼
react_retrieval node  ──  LLM (bound_tools) picks 1+ tools:
    │   hybrid_search_tool_react | bm25_search_tool_react |
    │   vector_search_tool_react | jira_search_react | jira_project_health_react
    ▼
expand_query()  ──  LLM generates 2 alternate phrasings (rag_qa / hybrid_qa only)
    │               [original, alt1, alt2]
    ▼
For each query variant:
    ├── BM25 search (SQLite FTS5)
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

### ReAct tool selection — `graph/react_agent.py`
- `run_retrieval_react()` is the shared entry point for `rag_qa`, `jira_qa`, and `hybrid_qa` — replaces the old fixed `brd_retrieval` / `nl_to_jql` / `jira_search` nodes with one dynamic node
- ChatGroq bound to 5 `@tool`-wrapped functions; a system prompt gives explicit tool-selection rules (BRD questions → hybrid search, gap analysis → hybrid + project health, sprint/backlog scope → `scope` arg, targeted ticket listing → `jira_search_react` with example JQL)
- LLM emits `tool_calls`; each is executed directly against the matching plain callable (`_TOOL_EXECUTORS`), results split into `brd_docs` / `jira_docs` by tool name
- `hybrid_qa` always additionally force-fetches the full project backlog (`project = KEY ORDER BY updated DESC`, up to 50) merged in, because narrow ReAct searches would under-report coverage
- Falls back to deterministic retrieval (`_fallback_retrieval`) when Groq is disabled or the LLM makes no tool calls — mirrors the old hardcoded per-flow behaviour

### BM25 — `retrievers/bm25.py`
- Backend: native SQLite **FTS5** virtual table (`knowledge_fts`, `tokenize='porter ascii'`) via `database.fts_search()` — not the `rank-bm25` Python library
- Query built by `_escape_fts()`: lowercases, strips punctuation, tokenizes on whitespace, joins as `"tok1"* OR "tok2"* OR ...` (FTS5 prefix-match MATCH syntax)
- FTS5's built-in `bm25()` ranking function scores rows (lower = better; negated in code so higher = better, consistent with vector/rerank scores)
- Corpus kept in sync with the `knowledge` table on every insert (`add_document`) and ingestion run
- Each doc gets `bm25_score` in result metadata

### Vector Search — `retrievers/vector.py`
- Model: `BAAI/bge-small-en-v1.5` (384-dim, asymmetric retrieval) via `langchain_huggingface.HuggingFaceEmbeddings`
- Store: ChromaDB (`$DATA_DIR/chroma_db/`)
- Ingestion: `backend/scripts/ingest_brd.py` — chunk size 800, overlap 150
- BGE query prefix applied to the query only (not documents): `"Represent this sentence for searching relevant passages: {query}"`
- `encode_kwargs={"normalize_embeddings": True}` for cosine similarity
- Each doc gets `vector_score` in result metadata
- Project-scoped: `similarity_search_with_score(..., filter={"project_key": project_key})`; returns nothing (not unfiltered results) if no chunks are tagged for that project, to avoid cross-project leakage

> **Note:** switching embedding models changes vector dimensionality — the Chroma index must be rebuilt after any model change:
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
- All 3 queries searched independently through `hybrid_search_tool` (BM25 + vector + RRF + rerank already applied per variant)
- Results deduplicated by `id`/`title`, keeping the higher-scoring instance across variants, then re-sorted by `rerank_score`/`score` and capped to 8
- Increases vocabulary coverage: handles synonym mismatches between user query and indexed docs
- Falls back to original query only if LLM expansion fails
- Runs for `rag_qa` and `hybrid_qa` (post react_retrieval, on the BRD half of the docs) and for the `ticket` flow's dedicated retrieval node

## Data Flow (rag_qa flow)

```
user: "What does the BRD say about employee document upload limits?"
    │
    react_retrieval → LLM picks hybrid_search_tool_react → brd_docs (top 8)
    │
    expand_query → ["What does the BRD say about employee document upload limits?",
                    "Document upload size restrictions for employee portal",
                    "File upload constraints in EOMS specification"]
    │
    Each variant → hybrid_search_tool (BM25 + Vector + RRF + rerank) → dedup (keep best score per doc)
    │
    Merge with react_retrieval's initial docs, re-sort by rerank_score, top 8 sent to LLM as context
    │
    LLM answers citing source titles, with conversation history (last 6 turns) injected for continuity
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
