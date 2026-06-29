"""SQLite persistence: the `contents` table (mutable status) and the
append-only `audit_log` table.

Two tables because they have different lifecycles: a content row is updated in
place (status flips on appeal), while the audit log is an immutable trail of
events. Keeping them separate keeps the audit trail trustworthy.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contents (
                content_id   TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                text         TEXT NOT NULL,
                attribution  TEXT NOT NULL,
                confidence   REAL NOT NULL,
                p_ai         REAL NOT NULL,
                llm_score    REAL,
                style_score  REAL,
                lexical_score REAL,
                status       TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id   TEXT NOT NULL,
                event_type   TEXT NOT NULL,      -- 'classified' | 'appeal'
                timestamp    TEXT NOT NULL,
                payload      TEXT NOT NULL        -- full JSON event detail
            )
            """
        )


def save_content(row: dict) -> None:
    """Insert a freshly classified content row (status = 'classified')."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO contents (content_id, creator_id, text, attribution,
                confidence, p_ai, llm_score, style_score, lexical_score,
                status, created_at)
            VALUES (:content_id, :creator_id, :text, :attribution, :confidence,
                :p_ai, :llm_score, :style_score, :lexical_score, :status,
                :created_at)
            """,
            row,
        )


def get_content(content_id: str) -> dict | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM contents WHERE content_id = ?", (content_id,)
        )
        r = cur.fetchone()
        return dict(r) if r else None


def update_status(content_id: str, status: str) -> bool:
    """Flip a content's status (e.g. 'classified' -> 'under_review'). Returns
    True if a row was actually updated."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE contents SET status = ? WHERE content_id = ?",
            (status, content_id),
        )
        return cur.rowcount > 0


def append_audit(content_id: str, event_type: str, payload: dict) -> None:
    """Append one immutable event to the audit trail."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (content_id, event_type, timestamp, payload) "
            "VALUES (?, ?, ?, ?)",
            (content_id, event_type, _utcnow(), json.dumps(payload, ensure_ascii=False)),
        )


def recent_audit(limit: int = 20) -> list[dict]:
    """Most recent audit entries, newest first, with payload flattened in."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        entries = []
        for r in cur.fetchall():
            entry = {
                "content_id": r["content_id"],
                "event_type": r["event_type"],
                "timestamp": r["timestamp"],
            }
            entry.update(json.loads(r["payload"]))
            entries.append(entry)
        return entries
