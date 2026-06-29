"""SQLite persistence.

Tables:
  contents     — one row per submission, mutable status (flips on appeal).
                 Signal scores are stored as JSON so the schema is
                 modality-agnostic (text vs image_metadata; planning.md stretch).
  audit_log    — append-only trail of classification & appeal events.
  challenges   — pending verification challenges (provenance certificate).
  credentials  — issued "verified human" credentials.

contents and audit_log have different lifecycles (one is updated in place, the
other is immutable), so they stay separate to keep the audit trail trustworthy.
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
                content_type TEXT NOT NULL DEFAULT 'text',
                text         TEXT NOT NULL,
                attribution  TEXT NOT NULL,
                confidence   REAL NOT NULL,
                p_ai         REAL NOT NULL,
                signals_json TEXT NOT NULL,      -- {signal_name: score, ...}
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS challenges (
                challenge_id TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                phrase       TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                creator_id    TEXT PRIMARY KEY,
                credential_id TEXT NOT NULL,
                token         TEXT NOT NULL,
                issued_at     TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active'
            )
            """
        )


# --- contents ----------------------------------------------------------------
def save_content(row: dict) -> None:
    """Insert a freshly classified content row (status = 'classified').
    `row['signals']` is a dict of {signal_name: score}; stored as JSON."""
    data = dict(row)
    data["signals_json"] = json.dumps(data.pop("signals"), ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO contents (content_id, creator_id, content_type, text,
                attribution, confidence, p_ai, signals_json, status, created_at)
            VALUES (:content_id, :creator_id, :content_type, :text, :attribution,
                :confidence, :p_ai, :signals_json, :status, :created_at)
            """,
            data,
        )


def _content_row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["signals"] = json.loads(d.pop("signals_json"))
    return d


def get_content(content_id: str) -> dict | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM contents WHERE content_id = ?", (content_id,)
        )
        r = cur.fetchone()
        return _content_row_to_dict(r) if r else None


def all_contents() -> list[dict]:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM contents")
        return [_content_row_to_dict(r) for r in cur.fetchall()]


def update_status(content_id: str, status: str) -> bool:
    """Flip a content's status (e.g. 'classified' -> 'under_review'). Returns
    True if a row was actually updated."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE contents SET status = ? WHERE content_id = ?",
            (status, content_id),
        )
        return cur.rowcount > 0


# --- audit log ---------------------------------------------------------------
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


def count_appeals() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'appeal'")
        return cur.fetchone()["n"]


# --- verification challenges & credentials -----------------------------------
def save_challenge(challenge_id: str, creator_id: str, phrase: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO challenges (challenge_id, creator_id, phrase, used, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (challenge_id, creator_id, phrase, _utcnow()),
        )


def get_challenge(challenge_id: str) -> dict | None:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM challenges WHERE challenge_id = ?", (challenge_id,))
        r = cur.fetchone()
        return dict(r) if r else None


def mark_challenge_used(challenge_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE challenges SET used = 1 WHERE challenge_id = ?", (challenge_id,))


def save_credential(creator_id: str, credential_id: str, token: str) -> str:
    issued_at = _utcnow()
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO credentials (creator_id, credential_id, token, "
            "issued_at, status) VALUES (?, ?, ?, ?, 'active')",
            (creator_id, credential_id, token, issued_at),
        )
    return issued_at


def get_credential(creator_id: str) -> dict | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM credentials WHERE creator_id = ? AND status = 'active'",
            (creator_id,),
        )
        r = cur.fetchone()
        return dict(r) if r else None
