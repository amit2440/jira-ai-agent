# Database Schema

## SQLite (POC)

Location: `backend/knowledge.db` (or `$DATA_DIR/knowledge.db`)

### `runs` table

```sql
CREATE TABLE runs (
    run_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL   -- JSON-serialized RunState (events, result, status, total_tokens)
);
```

Denormalized: full `RunState` stored as a single JSON blob. Simple for POC; production should split into `runs` + `run_events` tables for queryable event history and immutable audit records.

### `knowledge` table

```sql
CREATE TABLE knowledge (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    content     TEXT,
    project_key TEXT DEFAULT NULL
);
```

`project_key` column was added via `ALTER TABLE` (backward-compatible). `ingest_brd.py` deletes then re-inserts rows for a given `project_key` on each ingestion run. Documents added via `/api/knowledge` API have `project_key` set from the request context.

BM25 search (`retrievers/bm25.py`) reads from this table, filtered by `project_key`.

## ChromaDB (vector store)

Location: `backend/chroma_db/` (or `$DATA_DIR/chroma_db/`)

- Embedding model: `BAAI/bge-large-en-v1.5` (1024-dim)
- Collection: single unnamed collection per Chroma instance
- Metadata per chunk: `title`, `project_key`, `page` (PDF page number), chunk index
- Populated by: `backend/scripts/ingest_brd.py`

> **Rebuild required** after switching embedding models (e.g. from MiniLM to BGE-large) — different dimensions make the old index incompatible:
> ```bash
> python backend/scripts/ingest_brd.py --project-key EOMS
> ```
> Script clears the existing Chroma directory (`shutil.rmtree`) before re-ingesting.

## Exports

Location: `backend/exports/`

Report files written by `tools/export.py` as `<run_id>-<title>.md`. No database entry; plain filesystem.

## Production Recommendations

| Concern | POC | Production |
|---|---|---|
| Run persistence | SQLite JSON blob | Postgres with normalized `runs` + `run_events` tables |
| Vector store | Local ChromaDB | Managed service (Pinecone, Weaviate, pgvector) |
| Knowledge store | SQLite | Postgres with full-text search extension |
| Export storage | Local filesystem | S3 / GCS with signed URLs |
| Migrations | Manual `ALTER TABLE` | Alembic migration scripts |
