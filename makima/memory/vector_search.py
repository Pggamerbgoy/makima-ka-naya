"""
Makima v2 — Vector Search Engine (Step 10.3).
Architectural Pattern: fastembed (pure Python, no PyTorch) + sqlite-vec for
on-device semantic similarity search without external API keys or GPU requirements.

Design decisions:
- fastembed uses ONNX Runtime under the hood — zero PyTorch dependency.
- sqlite-vec stores float32 vectors in a SQLite virtual table (vec0).
- Graceful degradation: if sqlite-vec extension fails to load, falls back to
  cosine similarity computed in Python against in-memory embeddings.
- Separate SQLite DB file (vector_store.db) from episodic history.db to avoid
  WAL mode conflicts between two different write patterns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("makima.memory.vector_search")

# ---------------------------------------------------------------------------
# Optional imports — graceful degradation if sqlite-vec is unavailable
# ---------------------------------------------------------------------------
try:
    import sqlite_vec  # noqa: F401  — registers vec0 via sqlite3 extension

    _HAS_SQLITE_VEC = True
except ImportError:
    _HAS_SQLITE_VEC = False
    logger.warning(
        "sqlite-vec not available. VectorSearchEngine will use in-memory cosine fallback."
    )

try:
    from fastembed import TextEmbedding

    _HAS_FASTEMBED = True
except ImportError:
    TextEmbedding = None  # type: ignore
    _HAS_FASTEMBED = False
    logger.error(
        "fastembed not installed. VectorSearchEngine cannot generate embeddings. "
        "Install with: pip install fastembed"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode_vector(v: List[float]) -> bytes:
    """Packs a float list into little-endian float32 bytes for sqlite-vec."""
    return struct.pack(f"{len(v)}f", *v)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity — used as fallback when sqlite-vec is absent."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# VectorSearchEngine
# ---------------------------------------------------------------------------

class VectorSearchEngine:
    """
    On-device semantic search for Makima episodic memory.

    Usage:
        engine = VectorSearchEngine()
        await engine.connect()
        await engine.add_document("turn:123", "The user asked about Python async IO")
        results = await engine.search("asyncio coroutines", top_k=5)
        await engine.close()
    """

    # Default embedding model — multilingual MiniLM-L6, ~22MB, no GPU
    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    VECTOR_DIM = 384  # dimension for MiniLM-L12

    # In-memory LRU embedding cache to eliminate redundant inference
    _EMBED_CACHE: Dict[str, List[float]] = {}
    _CACHE_MAX_SIZE: int = 1000

    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        model_name: Optional[str] = None,
        vector_dim: Optional[int] = None,
    ) -> None:
        """
        Args:
            db_path: Path to the SQLite vector store. Defaults to
                     ~/.makima/state/vector_store.db, or ':memory:' for tests.
            model_name: fastembed model name. Defaults dynamically to settings.yaml.
            vector_dim: Vector dimensions. Defaults dynamically to settings.yaml (384).
        """
        if db_path is None:
            try:
                from makima.config import get_settings

                settings = get_settings()
                base = Path(settings.sqlite_db_path).parent
            except Exception:
                base = Path.home() / ".makima" / "state"
            self.db_path: Union[Path, str] = base / "vector_store.db"
        elif db_path == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)

        # Dynamic model & dimension configuration
        if model_name is None or vector_dim is None:
            try:
                from makima.config import get_settings
                settings = get_settings()
                self.model_name = model_name or getattr(settings.memory.vector_search, "embedding_model", self.DEFAULT_MODEL)
                self.vector_dim = vector_dim or getattr(settings.memory.vector_search, "dimension", self.VECTOR_DIM)
            except Exception:
                self.model_name = model_name or self.DEFAULT_MODEL
                self.vector_dim = vector_dim or self.VECTOR_DIM
        else:
            self.model_name = model_name
            self.vector_dim = vector_dim

        self._conn: Optional[sqlite3.Connection] = None
        self._embedder: Optional[Any] = None
        self._lock = asyncio.Lock()

        # Fallback: in-memory index when sqlite-vec is unavailable
        self._fallback_docs: List[Dict[str, Any]] = []  # [{id, text, vector}]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _sync_connect(self) -> None:
        """Internal synchronous setup of SQLite and vec0 virtual table."""
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_metadata (
                doc_id         TEXT PRIMARY KEY,
                text           TEXT NOT NULL,
                metadata       TEXT,
                embedding_json TEXT
            );
            """
        )

        if _HAS_SQLITE_VEC:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)  # type: ignore[attr-defined]
            conn.enable_load_extension(False)

            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents USING vec0(
                    doc_id TEXT PRIMARY KEY,
                    embedding FLOAT[{self.vector_dim}]
                );
                """
            )
            logger.info(
                f"VectorSearchEngine connected (sqlite-vec {sqlite_vec.__version__}) "  # type: ignore[union-attr]
                f"→ {self.db_path}"
            )
        else:
            rows = conn.execute("SELECT doc_id, text, metadata, embedding_json FROM doc_metadata;").fetchall()
            self._fallback_docs = [
                {
                    "id": r["doc_id"],
                    "text": r["text"],
                    "vector": json.loads(r["embedding_json"]) if r["embedding_json"] else [],
                    "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
                }
                for r in rows if r["embedding_json"]
            ]
            logger.info(
                f"VectorSearchEngine connected (fallback cosine mode with {len(self._fallback_docs)} persisted docs) → {self.db_path}"
            )

        conn.commit()
        self._conn = conn

    async def connect(self) -> None:
        """Opens the SQLite connection and sets up the vec0 virtual table off the main event loop."""
        async with self._lock:
            if self._conn is not None:
                return
            await asyncio.to_thread(self._sync_connect)

    def _get_embedder(self) -> Any:
        """Lazy-loads the fastembed TextEmbedding model (downloads on first use)."""
        if self._embedder is None:
            if not _HAS_FASTEMBED:
                raise RuntimeError(
                    "fastembed is not installed. Run: pip install fastembed"
                )
            logger.info(f"Loading embedding model: {self.model_name} …")
            self._embedder = TextEmbedding(model_name=self.model_name)
            logger.info("Embedding model loaded.")
        return self._embedder

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generates embeddings synchronously with in-memory LRU caching."""
        results: List[Optional[List[float]]] = [None] * len(texts)
        missing_indices: List[int] = []
        missing_texts: List[str] = []

        for idx, t in enumerate(texts):
            cached = self._EMBED_CACHE.get(t)
            if cached is not None:
                results[idx] = cached
            else:
                missing_indices.append(idx)
                missing_texts.append(t)

        if missing_texts:
            embedder = self._get_embedder()
            computed = [list(map(float, v)) for v in embedder.embed(missing_texts)]
            for idx, text, vec in zip(missing_indices, missing_texts, computed):
                results[idx] = vec
                if len(self._EMBED_CACHE) >= self._CACHE_MAX_SIZE:
                    try:
                        first_k = next(iter(self._EMBED_CACHE))
                        self._EMBED_CACHE.pop(first_k, None)
                    except StopIteration:
                        pass
                self._EMBED_CACHE[text] = vec

        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Core Operations
    # ------------------------------------------------------------------

    async def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Embeds and stores a document in the vector index.

        Args:
            doc_id: Unique identifier (e.g. 'turn:123', 'skill:cleanup').
            text: The text content to embed and index.
            metadata: Optional JSON-serialisable metadata dict.
        """
        if not text or not text.strip():
            return

        await self.connect()

        # Embed in thread to avoid blocking the event loop
        vector = await asyncio.to_thread(self._embed, [text])
        vec = vector[0]

        metadata_str = json.dumps(metadata, ensure_ascii=False) if metadata else None

        async with self._lock:
            def _sync_add():
                conn = self._conn
                assert conn is not None

                if _HAS_SQLITE_VEC:
                    # Upsert into sqlite-vec virtual table
                    conn.execute(
                        "DELETE FROM vec_documents WHERE doc_id = ?;", (doc_id,)
                    )
                    conn.execute(
                        "INSERT INTO vec_documents (doc_id, embedding) VALUES (?, ?);",
                        (doc_id, _encode_vector(vec)),
                    )
                    conn.execute(
                        """
                        INSERT INTO doc_metadata (doc_id, text, metadata, embedding_json)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(doc_id) DO UPDATE SET text=excluded.text, metadata=excluded.metadata;
                        """,
                        (doc_id, text, metadata_str, None),
                    )
                    conn.commit()
                else:
                    # Fallback: in-memory list + persistent SQLite storage
                    embedding_json = json.dumps(vec)
                    conn.execute(
                        """
                        INSERT INTO doc_metadata (doc_id, text, metadata, embedding_json)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(doc_id) DO UPDATE SET text=excluded.text, metadata=excluded.metadata, embedding_json=excluded.embedding_json;
                        """,
                        (doc_id, text, metadata_str, embedding_json),
                    )
                    conn.commit()
                    self._fallback_docs = [d for d in self._fallback_docs if d["id"] != doc_id]
                    self._fallback_docs.append(
                        {"id": doc_id, "text": text, "vector": vec, "metadata": metadata}
                    )

            await asyncio.to_thread(_sync_add)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Semantic similarity search.

        Args:
            query: Free-text search query.
            top_k: Maximum number of results to return.
            min_score: Minimum cosine similarity threshold [0, 1].

        Returns:
            List of dicts: [{doc_id, text, score, metadata}] ordered by score desc.
        """
        if not query or not query.strip():
            return []

        await self.connect()

        q_vector = await asyncio.to_thread(self._embed, [query])
        q_vec = q_vector[0]

        async with self._lock:
            def _sync_search():
                conn = self._conn
                assert conn is not None

                if _HAS_SQLITE_VEC:
                    # sqlite-vec KNN query
                    rows = conn.execute(
                        """
                        SELECT v.doc_id, m.text, m.metadata, v.distance
                        FROM vec_documents v
                        JOIN doc_metadata m ON m.doc_id = v.doc_id
                        WHERE v.embedding MATCH ?
                          AND k = ?
                        ORDER BY v.distance ASC;
                        """,
                        (_encode_vector(q_vec), top_k),
                    ).fetchall()

                    results = []
                    for row in rows:
                        # For normalized vectors: cosine_sim = 1 - (L2_distance^2) / 2
                        dist = float(row["distance"])
                        score = max(0.0, 1.0 - (dist * dist) / 2.0)
                        if score < min_score:
                            continue
                        meta = None
                        if row["metadata"]:
                            try:
                                meta = json.loads(row["metadata"])
                            except Exception:
                                meta = row["metadata"]
                        results.append(
                            {
                                "doc_id": row["doc_id"],
                                "text": row["text"],
                                "score": round(score, 4),
                                "metadata": meta,
                            }
                        )
                    return results

                else:
                    # Fallback: brute-force cosine over in-memory list
                    scored = []
                    for doc in self._fallback_docs:
                        score = _cosine_similarity(q_vec, doc["vector"])
                        if score >= min_score:
                            scored.append((score, doc))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    return [
                        {
                            "doc_id": d["id"],
                            "text": d["text"],
                            "score": round(s, 4),
                            "metadata": d["metadata"],
                        }
                        for s, d in scored[:top_k]
                    ]

            return await asyncio.to_thread(_sync_search)

    async def delete_document(self, doc_id: str) -> bool:
        """Removes a document from the index. Returns True if found and deleted."""
        await self.connect()
        async with self._lock:
            conn = self._conn
            assert conn is not None

            if _HAS_SQLITE_VEC:
                conn.execute("DELETE FROM vec_documents WHERE doc_id = ?;", (doc_id,))
                cur = conn.execute(
                    "DELETE FROM doc_metadata WHERE doc_id = ?;", (doc_id,)
                )
                conn.commit()
                return (cur.rowcount or 0) > 0
            else:
                before = len(self._fallback_docs)
                self._fallback_docs = [d for d in self._fallback_docs if d["id"] != doc_id]
                return len(self._fallback_docs) < before

    async def document_count(self) -> int:
        """Returns the number of indexed documents."""
        await self.connect()
        async with self._lock:
            conn = self._conn
            assert conn is not None

            if _HAS_SQLITE_VEC:
                row = conn.execute("SELECT COUNT(*) FROM doc_metadata;").fetchone()
                return row[0] if row else 0
            else:
                return len(self._fallback_docs)

    async def close(self) -> None:
        """Closes the SQLite connection and truncates the WAL log."""
        async with self._lock:
            if self._conn is not None:
                def _sync_close():
                    if self._conn is not None:
                        try:
                            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                            self._conn.execute("PRAGMA optimize;")
                        except Exception:
                            pass
                        self._conn.close()
                        self._conn = None
                await asyncio.to_thread(_sync_close)
                logger.debug("VectorSearchEngine closed with WAL truncation.")

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> VectorSearchEngine:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
