"""
Makima v2 — Episodic Memory Engine.
Architectural Pattern: Async SQLite WAL Database via aiosqlite with FTS5 Full-Text Search.
Zero-Hardcoding Guarantee: Fully dynamic paths, auto-directory creation, and non-blocking async IO.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite

from makima.config import get_settings, resolve_path

logger = logging.getLogger("makima.memory.episodic")

# Gracefully import canonical provider models if available
try:
    from makima.provider.adapters.base import Message, ToolCall
except ImportError:
    Message = None  # type: ignore
    ToolCall = None  # type: ignore


class EpisodicMemory:
    """
    Asynchronous conversation store and episodic memory for Makima v2.
    Persists dialogue turns, tool invocations, and metadata into SQLite with WAL mode enabled.
    Provides fast chronological context window reconstruction and FTS5 full-text search.
    """

    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        fts_enabled: bool = True,
    ) -> None:
        """
        Initialize EpisodicMemory.

        Args:
            db_path: Path to the SQLite database file, or ':memory:'.
                     Defaults to settings.sqlite_db_path (~/.makima/state/history.db).
            fts_enabled: Whether to enable SQLite FTS5 index for full-text keyword retrieval.
        """
        if db_path is None:
            try:
                self.db_path: Union[Path, str] = get_settings().sqlite_db_path
            except Exception:
                self.db_path = Path.home() / ".makima" / "state" / "history.db"
        elif db_path == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = resolve_path(db_path)

        self.fts_enabled: bool = fts_enabled
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> aiosqlite.Connection:
        """
        Opens the SQLite database connection, enables WAL mode, and verifies table schemas.
        Thread/async safe.
        """
        async with self._lock:
            if self._db is not None:
                return self._db

            if isinstance(self.db_path, Path):
                self.db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = await aiosqlite.connect(str(self.db_path))
            conn.row_factory = aiosqlite.Row

            # 1. Enable WAL mode for high concurrent throughput & resilience
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.execute("PRAGMA busy_timeout=5000;")

            # 2. Create core relational tables
            await self._create_tables(conn)

            self._db = conn
            logger.info(f"EpisodicMemory connected to {self.db_path} (WAL enabled)")
            return self._db

    async def _create_tables(self, conn: aiosqlite.Connection) -> None:
        """Initializes tables and indices."""
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                timestamp REAL NOT NULL,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, turn_index)
            );
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_session_turn ON conversation_turns(session_id, turn_index);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_session_time ON conversation_turns(session_id, timestamp);"
        )

        # FTS5 Virtual Table for full-text search
        if self.fts_enabled:
            try:
                await conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                        session_id,
                        role UNINDEXED,
                        content,
                        tokenize = 'porter unicode61'
                    );
                    """
                )
            except Exception as e:
                logger.warning(f"Could not initialize FTS5 table: {e}. Falling back to standard search.")
                self.fts_enabled = False

        await conn.commit()

    async def _get_conn(self) -> aiosqlite.Connection:
        """Internal helper returning an active connection."""
        if self._db is None:
            return await self.connect()
        return self._db

    async def get_journal_mode(self) -> str:
        """Returns the active SQLite journal mode (e.g. 'wal' or 'memory')."""
        conn = await self._get_conn()
        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        return str(row[0]).lower() if row else ""

    async def store_turn(
        self,
        session_id: str,
        turn_index: Optional[int] = None,
        role: str = "user",
        content: str = "",
        tool_calls: Optional[Union[List[Any], Dict[str, Any], str]] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[Union[Dict[str, Any], str]] = None,
    ) -> int:
        """
        Stores a dialogue turn into the episodic store.

        Args:
            session_id: Unique session or conversation identifier.
            turn_index: Optional 0-indexed turn position. If omitted, automatically computes the next index.
            role: Speaker role ('user', 'assistant', 'system', 'tool').
            content: Raw text content of the message.
            tool_calls: Structured tool calls (JSON string, list of dicts, or list of ToolCall models).
            timestamp: Epoch timestamp in seconds. Defaults to time.time().
            metadata: Optional dictionary or JSON string of execution metadata (model, tokens, latency).

        Returns:
            The unique integer primary key (id) of the stored turn.
        """
        conn = await self._get_conn()

        if timestamp is None:
            timestamp = time.time()

        # Serialize tool_calls if necessary
        tool_calls_str: Optional[str] = None
        if tool_calls is not None:
            if isinstance(tool_calls, str):
                tool_calls_str = tool_calls
            elif isinstance(tool_calls, list):
                dumped = []
                for item in tool_calls:
                    if hasattr(item, "model_dump"):
                        dumped.append(item.model_dump())
                    elif isinstance(item, dict):
                        dumped.append(item)
                    else:
                        dumped.append(str(item))
                tool_calls_str = json.dumps(dumped, ensure_ascii=False)
            elif isinstance(tool_calls, dict):
                tool_calls_str = json.dumps(tool_calls, ensure_ascii=False)
            else:
                tool_calls_str = str(tool_calls)

        # Serialize metadata if necessary
        metadata_str: Optional[str] = None
        if metadata is not None:
            if isinstance(metadata, str):
                metadata_str = metadata
            elif isinstance(metadata, dict):
                metadata_str = json.dumps(metadata, ensure_ascii=False)
            else:
                metadata_str = str(metadata)

        async with self._lock:
            # Auto-compute turn_index if not supplied
            if turn_index is None:
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM conversation_turns WHERE session_id = ?;",
                    (session_id,),
                )
                row = await cursor.fetchone()
                turn_index = row[0] if row else 0

            # Upsert into conversation_turns
            cursor = await conn.execute(
                """
                INSERT INTO conversation_turns (
                    session_id, turn_index, role, content, tool_calls, timestamp, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, turn_index) DO UPDATE SET
                    role = excluded.role,
                    content = excluded.content,
                    tool_calls = excluded.tool_calls,
                    timestamp = excluded.timestamp,
                    metadata = excluded.metadata
                RETURNING id;
                """,
                (
                    session_id,
                    turn_index,
                    role,
                    content,
                    tool_calls_str,
                    timestamp,
                    metadata_str,
                ),
            )
            row = await cursor.fetchone()
            if not row:
                raise RuntimeError("Failed to store turn into database.")
            turn_id: int = row[0]

            # Synchronize FTS5 index
            if self.fts_enabled:
                try:
                    await conn.execute("DELETE FROM turns_fts WHERE rowid = ?;", (turn_id,))
                    await conn.execute(
                        "INSERT INTO turns_fts (rowid, session_id, role, content) VALUES (?, ?, ?, ?);",
                        (turn_id, session_id, role, content or ""),
                    )
                except Exception:
                    try:
                        await conn.execute("DELETE FROM turns_fts WHERE turn_id = ?;", (turn_id,))
                        await conn.execute(
                            "INSERT INTO turns_fts (turn_id, session_id, role, content) VALUES (?, ?, ?, ?);",
                            (turn_id, session_id, role, content or ""),
                        )
                    except Exception as e:
                        logger.debug(f"FTS indexing skipped: {e}")

            await conn.commit()
            return turn_id

    async def get_recent_turns(
        self,
        session_id: str,
        limit: int = 100,
        role: Optional[str] = None,
        order: str = "asc",
    ) -> List[Dict[str, Any]]:
        """
        Retrieves the most recent conversation turns for a given session.

        Args:
            session_id: Target session identifier.
            limit: Maximum number of recent turns to retrieve. Defaults to 100 to fit full ~286K context.
            role: Optional role filter ('user', 'assistant', etc.).
            order: 'asc' returns turns in chronological order (oldest to newest within recent window),
                   'desc' returns newest first. Default is 'asc'.

        Returns:
            List of turn dictionaries with parsed JSON tool_calls and metadata.
        """
        conn = await self._get_conn()

        query = """
            SELECT id, session_id, turn_index, role, content, tool_calls, timestamp, metadata, created_at
            FROM conversation_turns
            WHERE session_id = ?
        """
        params: List[Any] = [session_id]

        if role is not None:
            query += " AND role = ?"
            params.append(role)

        query += " ORDER BY turn_index DESC LIMIT ?;"
        params.append(limit)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        turns: List[Dict[str, Any]] = []
        for row in rows:
            parsed_tools = None
            if row["tool_calls"]:
                try:
                    parsed_tools = json.loads(row["tool_calls"])
                except Exception:
                    parsed_tools = row["tool_calls"]

            parsed_metadata = None
            if row["metadata"]:
                try:
                    parsed_metadata = json.loads(row["metadata"])
                except Exception:
                    parsed_metadata = row["metadata"]

            turns.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "turn_index": row["turn_index"],
                    "role": row["role"],
                    "content": row["content"],
                    "tool_calls": parsed_tools,
                    "timestamp": row["timestamp"],
                    "metadata": parsed_metadata,
                    "created_at": row["created_at"],
                }
            )

        if order == "asc":
            turns.reverse()

        return turns

    @staticmethod
    def _parse_tool_call(c: Any) -> Optional[Any]:
        """Safely parses raw dictionaries or ToolCall objects into canonical ToolCall models."""
        if ToolCall is None:
            return None
        if isinstance(c, ToolCall):
            return c
        if not isinstance(c, dict):
            return None
        if "function" in c and isinstance(c["function"], dict):
            fn = c["function"]
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            return ToolCall(
                id=str(c.get("id", "")),
                name=str(fn.get("name", "")),
                arguments=args if isinstance(args, dict) else {"value": args},
            )
        try:
            return ToolCall(**c)
        except Exception:
            return ToolCall(
                id=str(c.get("id", "")),
                name=str(c.get("name", "")),
                arguments=c.get("arguments", {}) if isinstance(c.get("arguments"), dict) else {},
            )

    async def get_messages_by_token_budget(
        self,
        session_id: str,
        max_tokens: int,
        token_counter: Optional[Any] = None,
        max_messages: int = 5000,
    ) -> List[Any]:
        """
        Retrieves recent turns converted to canonical Message objects, bounded by a total
        token budget (rather than an arbitrary fixed message count).

        Guarantees:
          1. Walks backward from most recent turn to oldest turn.
          2. Preserves Atomic Tool Pair Invariant: Groups assistant tool calls and their
             corresponding tool responses into atomic clusters so neither is ever orphaned.
          3. Sane Bounds: Caps the maximum rows fetched from SQLite at `max_messages` (default 5,000).
          4. Returns messages in ascending chronological order ('asc').
        """
        turns = await self.get_recent_turns(session_id=session_id, limit=max_messages, order="asc")
        if not turns:
            return []

        if Message is None:
            return turns

        messages: List[Any] = []
        for t in turns:
            parsed_calls = None
            if t["tool_calls"] and ToolCall is not None:
                if isinstance(t["tool_calls"], list):
                    parsed_calls = []
                    for c in t["tool_calls"]:
                        call_obj = self._parse_tool_call(c)
                        if call_obj is not None:
                            parsed_calls.append(call_obj)

            meta_dict = t["metadata"] if isinstance(t.get("metadata"), dict) else {}
            messages.append(
                Message(
                    role=t["role"],
                    content=t["content"],
                    tool_calls=parsed_calls,
                    tool_call_id=meta_dict.get("tool_call_id"),
                    name=meta_dict.get("name"),
                )
            )

        if not messages:
            return []

        def _count_msg(msg: Any) -> int:
            if token_counter is not None and hasattr(token_counter, "count_message"):
                try:
                    return token_counter.count_message(msg)
                except Exception:
                    pass
            try:
                from makima.core.context import TokenCounter
                return TokenCounter().count_message(msg)
            except Exception:
                pass
            cnt = 4
            if getattr(msg, "role", None):
                cnt += len(str(msg.role)) // 4 + 1
            if getattr(msg, "content", None):
                cnt += len(str(msg.content)) // 4 + 1
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    cnt += 8
                    cnt += len(str(getattr(tc, "name", ""))) // 4 + 1
                    args = getattr(tc, "arguments", {})
                    if args:
                        cnt += len(str(args)) // 4 + 1
            return max(1, cnt)

        # Group messages into atomic execution blocks to preserve tool call/result pairing
        blocks: List[List[Any]] = []
        curr_block: List[Any] = []

        for m in messages:
            if m.role == "tool":
                curr_block.append(m)
            elif m.role == "assistant" and m.tool_calls:
                if curr_block:
                    blocks.append(curr_block)
                curr_block = [m]
            else:
                if curr_block:
                    blocks.append(curr_block)
                    curr_block = []
                blocks.append([m])

        if curr_block:
            blocks.append(curr_block)

        # Accumulate blocks backwards from newest to oldest
        accumulated_blocks: List[List[Any]] = []
        total_tokens = 0

        for b in reversed(blocks):
            block_tokens = sum(_count_msg(m) for m in b)
            if accumulated_blocks and (total_tokens + block_tokens > max_tokens):
                break
            accumulated_blocks.append(b)
            total_tokens += block_tokens

        accumulated_blocks.reverse()
        result_messages: List[Any] = [m for b in accumulated_blocks for m in b]

        return result_messages

    async def get_recent_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
        token_counter: Optional[Any] = None,
    ) -> List[Any]:
        """
        Retrieves recent turns converted directly into canonical Message objects.
        If `max_tokens` is provided, dynamically loads history up to the token budget
        with atomic tool pair preservation.
        Otherwise falls back to count-based `limit` (defaulting to 100).
        """
        if max_tokens is not None and max_tokens > 0:
            return await self.get_messages_by_token_budget(
                session_id=session_id,
                max_tokens=max_tokens,
                token_counter=token_counter,
                max_messages=limit or 5000,
            )

        eff_limit = limit if limit is not None else 100
        turns = await self.get_recent_turns(session_id=session_id, limit=eff_limit, order="asc")
        if Message is None:
            return turns

        messages = []
        for t in turns:
            parsed_calls = None
            if t["tool_calls"] and ToolCall is not None:
                if isinstance(t["tool_calls"], list):
                    parsed_calls = []
                    for c in t["tool_calls"]:
                        call_obj = self._parse_tool_call(c)
                        if call_obj is not None:
                            parsed_calls.append(call_obj)

            meta_dict = t["metadata"] if isinstance(t.get("metadata"), dict) else {}
            messages.append(
                Message(
                    role=t["role"],
                    content=t["content"],
                    tool_calls=parsed_calls,
                    tool_call_id=meta_dict.get("tool_call_id"),
                    name=meta_dict.get("name"),
                )
            )
        return messages

    async def search_fts(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Performs full-text search across dialogue turns.
        Uses FTS5 with prefix matching when available, with automatic fallback to LIKE search.

        Args:
            query: Free-text search terms.
            session_id: Optional session filter.
            limit: Maximum matching turns to return.

        Returns:
            List of matching turn dicts ordered by relevance rank.
        """
        conn = await self._get_conn()

        fts_reserved = {"and", "or", "not", "near"}
        tokens = [t for t in re.findall(r"\w+", query) if t.lower() not in fts_reserved]
        if not tokens:
            return []

        # If FTS is enabled, execute FTS5 MATCH
        if self.fts_enabled:
            fts_query = " AND ".join(f'"{t}"*' for t in tokens[:12])
            sql = """
                SELECT c.id, c.session_id, c.turn_index, c.role, c.content, c.tool_calls, c.timestamp, c.metadata, fts.rank
                FROM turns_fts fts
                JOIN conversation_turns c ON (c.id = fts.rowid)
                WHERE turns_fts MATCH ?
            """
            params: List[Any] = [fts_query]

            if session_id is not None:
                sql += " AND c.session_id = ?"
                params.append(session_id)

            sql += " ORDER BY fts.rank ASC LIMIT ?;"
            params.append(limit)

            try:
                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    parsed_tools = None
                    if row["tool_calls"]:
                        try:
                            parsed_tools = json.loads(row["tool_calls"])
                        except Exception:
                            parsed_tools = row["tool_calls"]
                    results.append(
                        {
                            "id": row["id"],
                            "session_id": row["session_id"],
                            "turn_index": row["turn_index"],
                            "role": row["role"],
                            "content": row["content"],
                            "tool_calls": parsed_tools,
                            "timestamp": row["timestamp"],
                            "rank": row["rank"],
                        }
                    )
                return results
            except Exception as e:
                logger.warning(f"FTS search error: {e}. Executing fallback LIKE search.")

        # Fallback LIKE search
        like_pattern = f"%{'%'.join(tokens)}%"
        sql = """
            SELECT id, session_id, turn_index, role, content, tool_calls, timestamp, metadata, 0.0 as rank
            FROM conversation_turns
            WHERE content LIKE ?
        """
        params = [like_pattern]
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY turn_index DESC LIMIT ?;"
        params.append(limit)

        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            parsed_tools = None
            if row["tool_calls"]:
                try:
                    parsed_tools = json.loads(row["tool_calls"])
                except Exception:
                    parsed_tools = row["tool_calls"]
            results.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "turn_index": row["turn_index"],
                    "role": row["role"],
                    "content": row["content"],
                    "tool_calls": parsed_tools,
                    "timestamp": row["timestamp"],
                    "rank": 0.0,
                }
            )
        return results

    async def get_session_turn_count(self, session_id: str) -> int:
        """Returns the total number of turns stored for a session."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM conversation_turns WHERE session_id = ?;", (session_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists active sessions with turn count and latest activity."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """
            SELECT session_id, COUNT(*) as turn_count, MAX(timestamp) as last_active, MAX(turn_index) as max_turn
            FROM conversation_turns
            GROUP BY session_id
            ORDER BY last_active DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "session_id": row["session_id"],
                "turn_count": row["turn_count"],
                "last_active": row["last_active"],
                "max_turn": row["max_turn"],
            }
            for row in rows
        ]

    async def delete_session(self, session_id: str) -> int:
        """Deletes all conversation turns and FTS entries for a session."""
        conn = await self._get_conn()
        async with self._lock:
            if self.fts_enabled:
                try:
                    await conn.execute("DELETE FROM turns_fts WHERE session_id = ?;", (session_id,))
                except Exception:
                    pass
            cursor = await conn.execute(
                "DELETE FROM conversation_turns WHERE session_id = ?;", (session_id,)
            )
            deleted_count = cursor.rowcount
            await conn.commit()
            logger.info(f"Deleted session '{session_id}' ({deleted_count} turns removed)")
            return deleted_count

    async def clear_all(self) -> None:
        """Clears all conversation turns and FTS indices."""
        conn = await self._get_conn()
        async with self._lock:
            if self.fts_enabled:
                try:
                    await conn.execute("DELETE FROM turns_fts;")
                except Exception:
                    pass
            await conn.execute("DELETE FROM conversation_turns;")
            await conn.commit()
            logger.info("Cleared all episodic memory turns.")

    async def close(self) -> None:
        """Closes the database connection cleanly."""
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
                logger.debug("EpisodicMemory closed.")

    async def __aenter__(self) -> EpisodicMemory:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
