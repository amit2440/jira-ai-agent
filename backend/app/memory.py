"""
Conversational memory store — persists Q&A history per session_id in SQLite.

Each turn: { role: "user"|"assistant", content: str, flow: str, timestamp: str }
Max turns kept per session: MAX_HISTORY (oldest pruned first).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

_log = logging.getLogger("agent")

DB_PATH = DATA_DIR / "assistant.db"
MAX_HISTORY = 20  # turns (user + assistant pairs = 10 exchanges)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                flow      TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_history(session_id, id)"
        )


_ensure_table()


def get_history(session_id: str, limit: int = MAX_HISTORY) -> list[dict[str, Any]]:
    """Return last `limit` turns for session, oldest first."""
    if not session_id:
        return []
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT role, content, flow, timestamp FROM conversation_history "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception as exc:
        _log.warning(f"[Memory] get_history failed: {exc}")
        return []


def append_turn(session_id: str, role: str, content: str, flow: str | None = None) -> None:
    """Append one turn and prune oldest beyond MAX_HISTORY."""
    if not session_id:
        return
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO conversation_history(session_id, role, content, flow, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, flow, ts),
            )
            # Prune: keep only the latest MAX_HISTORY rows per session
            conn.execute(
                "DELETE FROM conversation_history WHERE session_id = ? AND id NOT IN ("
                "  SELECT id FROM conversation_history WHERE session_id = ? "
                "  ORDER BY id DESC LIMIT ?"
                ")",
                (session_id, session_id, MAX_HISTORY),
            )
    except Exception as exc:
        _log.warning(f"[Memory] append_turn failed: {exc}")


def clear_history(session_id: str) -> None:
    if not session_id:
        return
    try:
        with _conn() as conn:
            conn.execute(
                "DELETE FROM conversation_history WHERE session_id = ?", (session_id,)
            )
    except Exception as exc:
        _log.warning(f"[Memory] clear_history failed: {exc}")


def format_history_for_prompt(history: list[dict[str, Any]], max_turns: int = 6) -> str:
    """Format last max_turns as a compact conversation block for LLM injection."""
    if not history:
        return ""
    recent = history[-max_turns:]
    lines = []
    for turn in recent:
        prefix = "User" if turn["role"] == "user" else "Assistant"
        # Truncate long assistant answers to keep prompt size reasonable
        content = turn["content"]
        if turn["role"] == "assistant" and len(content) > 400:
            content = content[:400] + "…"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines)
