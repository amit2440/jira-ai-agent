import csv
import json
import sqlite3
import uuid
from pathlib import Path

from .config import DB_PATH
from .models import KnowledgeDocument, RunState

DB = DB_PATH


def connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, thread_id TEXT, payload TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, title TEXT, content TEXT)")
        # Add project_key column if not yet present (idempotent migration)
        try:
            conn.execute("ALTER TABLE knowledge ADD COLUMN project_key TEXT DEFAULT NULL")
        except Exception:
            pass
        conn.execute(
            "CREATE TABLE IF NOT EXISTS execution_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, thread_id TEXT, node TEXT, "
            "function_name TEXT, tool TEXT, payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        # FTS5 virtual table for native BM25 search (standalone, not a content table)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
            "id UNINDEXED, title, content, project_key UNINDEXED, "
            "tokenize='porter ascii')"
        )
        # Remove old generic seed docs (project_key IS NULL) — they contaminate project-scoped queries.
        conn.execute("DELETE FROM knowledge WHERE project_key IS NULL")
        conn.execute("DELETE FROM knowledge WHERE id LIKE 'csv_epic_%'")
def save_run(run: RunState) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, thread_id, payload) VALUES (?, ?, ?)",
            (run.run_id, run.thread_id, run.model_dump_json()),
        )


def get_run(run_id: str) -> RunState | None:
    with connection() as conn:
        row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return RunState.model_validate_json(row["payload"]) if row else None


def has_project_brd(project_key: str) -> bool:
    """True if at least one knowledge doc is tagged with this exact project_key."""
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM knowledge WHERE project_key = ? LIMIT 1", (project_key,)
        ).fetchone()
    return row is not None


def documents(project_key: str | None = None) -> list[dict]:
    with connection() as conn:
        if project_key:
            rows = conn.execute(
                "SELECT * FROM knowledge WHERE project_key = ?",
                (project_key,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM knowledge").fetchall()
        return [dict(row) for row in rows]


def add_document(doc: KnowledgeDocument) -> KnowledgeDocument:
    doc.id = doc.id or str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO knowledge (id, title, content, project_key) VALUES (?, ?, ?, ?)",
            (doc.id, doc.title, doc.content, doc.project_key),
        )
        # Keep FTS index in sync
        conn.execute(
            "INSERT INTO knowledge_fts(id, title, content, project_key) VALUES (?, ?, ?, ?)",
            (doc.id, doc.title, doc.content, doc.project_key),
        )
    return doc


def fts_search(query: str, limit: int = 5, project_key: str | None = None) -> list[dict]:
    """Native SQLite FTS5 BM25 search over the knowledge base."""
    with connection() as conn:
        if project_key:
            rows = conn.execute(
                "SELECT id, title, content, project_key, bm25(knowledge_fts) AS bm25_score "
                "FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? AND project_key = ? "
                "ORDER BY bm25_score LIMIT ?",
                (query, project_key, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, content, project_key, bm25(knowledge_fts) AS bm25_score "
                "FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? "
                "ORDER BY bm25_score LIMIT ?",
                (query, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def log_execution(
    *,
    run_id: str,
    thread_id: str,
    node: str,
    function_name: str,
    tool: str | None = None,
    payload: dict | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO execution_logs (run_id, thread_id, node, function_name, tool, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, thread_id, node, function_name, tool, json.dumps(payload or {})),
        )
