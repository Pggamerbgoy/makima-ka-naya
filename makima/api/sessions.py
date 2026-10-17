"""Local SQLite persistence for Makima conversation sessions.

The store is intentionally small and local-first: credentials and provider
state never enter this database.  All values are parameterized and bounded at
the API boundary before they reach SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


MAX_TITLE = 180
MAX_CONTENT = 500_000


def _now() -> float:
    return time.time()


def _clean_title(value: str) -> str:
    title = " ".join(str(value or "New session").split())[:MAX_TITLE]
    return title or "New session"


class SessionStore:
    """SQLite-backed sessions/messages/projects store."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    active_backend TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    parent_message_id TEXT,
                    variant_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
                """
            )

    @staticmethod
    def _session_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"], "title": row["title"], "project_id": row["project_id"],
            "active_backend": row["active_backend"], "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"], "message_count": int(row["message_count"]),
            "preview": row["preview"] or "",
        }

    def create_session(
        self,
        title: str = "New session",
        project_id: Optional[str] = None,
        active_backend: str = "",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_id = session_id or f"session_{uuid.uuid4().hex}"
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(id, title, project_id, active_backend, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (target_id, _clean_title(title), project_id, str(active_backend or "")[:160], now, now),
            )
        return self.get_session(target_id)  # type: ignore[return-value]

    def list_sessions(self, query: str = "", include_archived: bool = False, limit: int = 100) -> list[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query = " ".join(str(query or "").split())[:200]
        where = ["(s.archived = 0 OR ? = 1)"]
        params: list[Any] = [1 if include_archived else 0]
        if query:
            where.append("(s.title LIKE ? OR EXISTS (SELECT 1 FROM messages qm WHERE qm.session_id = s.id AND qm.content LIKE ?))")
            like = f"%{query}%"
            params.extend([like, like])
        with self._connect() as db:
            rows = db.execute(
                f"""SELECT s.*, COUNT(m.id) AS message_count,
                    (SELECT content FROM messages pm WHERE pm.session_id = s.id ORDER BY pm.created_at DESC LIMIT 1) AS preview
                    FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
                    WHERE {' AND '.join(where)} GROUP BY s.id
                    ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [self._session_row(row) for row in rows]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(
                """SELECT s.*, COUNT(m.id) AS message_count,
                   (SELECT content FROM messages pm WHERE pm.session_id = s.id ORDER BY pm.created_at DESC LIMIT 1) AS preview
                   FROM sessions s LEFT JOIN messages m ON m.session_id = s.id WHERE s.id = ? GROUP BY s.id""",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            result = self._session_row(row)
            result["messages"] = [dict(item) for item in db.execute(
                "SELECT id, role, content, parent_message_id, variant_id, metadata, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()]
            for message in result["messages"]:
                try:
                    message["metadata"] = json.loads(message["metadata"] or "{}")
                except (TypeError, ValueError):
                    message["metadata"] = {}
            return result

    def update_session(self, session_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        allowed = {"title", "project_id", "active_backend", "pinned", "archived"}
        values: Dict[str, Any] = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return self.get_session(session_id)
        if "title" in values:
            values["title"] = _clean_title(values["title"])
        if "active_backend" in values:
            values["active_backend"] = str(values["active_backend"] or "")[:160]
        for key in ("pinned", "archived"):
            if key in values:
                values[key] = int(bool(values[key]))
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as db:
            cursor = db.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", (*values.values(), session_id))
            if cursor.rowcount == 0:
                return None
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    def add_message(self, session_id: str, message_id: str, role: str, content: str, parent_message_id: Optional[str] = None, variant_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> bool:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Unsupported message role")
        with self._connect() as db:
            exists = db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if exists is None:
                return False
            now = _now()
            db.execute(
                "INSERT OR REPLACE INTO messages(id, session_id, role, content, parent_message_id, variant_id, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (message_id, session_id, role, str(content or "")[:MAX_CONTENT], parent_message_id, variant_id, json.dumps(metadata or {}, ensure_ascii=False)[:20_000], now),
            )
            db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return True

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return {"format": "makima-session-v1", "exported_at": _now(), "session": session}

