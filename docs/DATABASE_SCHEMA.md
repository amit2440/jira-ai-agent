# Database Schema

## SQLite — `assistant.db`

Location: `$DATA_DIR/assistant.db` (defaults to `backend/`)

### `runs` table

```sql
CREATE TABLE runs (
    run_id     TEXT PRIMARY KEY,
    thread_id  TEXT,
    payload    TEXT NOT NULL   -- JSON-serialized RunState (events, result, status, total_tokens)
);
```

Denormalized: full `RunState` stored as a single JSON blob, read/written by the legacy `/api/runs` endpoints. Live `/api/chat` traffic is checkpointed by LangGraph instead (see below), not through this table.

### `knowledge` table + `knowledge_fts` (FTS5)

```sql
CREATE TABLE knowledge (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    content     TEXT,
    project_key TEXT DEFAULT NULL
);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    id UNINDEXED, title, content, project_key UNINDEXED,
    tokenize='porter ascii'
);
```

`project_key` column was added via `ALTER TABLE` (backward-compatible). `ingest_brd.py` deletes then re-inserts rows for a given `project_key` on each ingestion run; every insert into `knowledge` is mirrored into `knowledge_fts`. Documents added via `/api/knowledge` API have `project_key` set from the request context and are searchable in `knowledge_fts` immediately.

BM25 search (`retrievers/bm25.py` → `database.fts_search`) queries `knowledge_fts` directly with SQLite's native `bm25()` ranking function, filtered by `project_key` — no external BM25 library or in-memory corpus.

### `conversation_history` table

```sql
CREATE TABLE conversation_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,   -- "user" | "assistant"
    content    TEXT NOT NULL,
    flow       TEXT,
    timestamp  TEXT NOT NULL
);
CREATE INDEX idx_conv_session ON conversation_history(session_id, id);
```

Managed by `memory.py`. Capped at 20 rows per `session_id` — oldest pruned on every insert. Backs the conversational-memory feature (last 6 turns injected into Q&A prompts).

### `execution_logs` table

```sql
CREATE TABLE execution_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT, thread_id TEXT, node TEXT,
    function_name TEXT, tool TEXT, payload TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Written by `jira_tool` and `report_export` nodes (`database.log_execution`) — an audit trail of side-effecting tool calls, separate from the in-memory `TimelineEvent` trace returned to the UI.

## SQLite — `checkpoints.db` (LangGraph state)

Location: `$DATA_DIR/checkpoints.db`

Managed entirely by `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` (its own internal schema, not application-defined tables). Stores a full snapshot of `GraphState` at every node boundary, keyed by `thread_id` (= `run_id`). This is what makes `interrupt()`-based human approval durable across process restarts — falls back to in-memory `MemorySaver` if no checkpointer is passed to `build_graph()`.

## ChromaDB (vector store)

Location: `$DATA_DIR/chroma_db/`

- Embedding model: `BAAI/bge-small-en-v1.5` (384-dim)
- Collection: single unnamed collection per Chroma instance
- Metadata per chunk: `title`, `project_key`, `page` (PDF page number), chunk index
- Populated by: `backend/scripts/ingest_brd.py` (chunk size 800, overlap 150)

> **Rebuild required** after switching embedding models — different dimensions make the old index incompatible:
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
