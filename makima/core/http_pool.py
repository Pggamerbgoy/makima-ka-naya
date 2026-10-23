"""
makima/core/http_pool.py — Persistent Singleton HTTP Client Pool.

Provides a centralized, persistent httpx.AsyncClient singleton configured
with HTTP/2 support and connection pooling (keepalive and total connection limits).
Ensures loop-awareness to safely reinitialize if the asyncio event loop changes or if
the client has been closed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Module-level singleton state
_shared_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None
_lock: Optional[asyncio.Lock] = None
_lock_loop: Optional[asyncio.AbstractEventLoop] = None
_shared_sync_client: Optional[httpx.Client] = None
_sync_lock = threading.Lock()


def _get_lock(loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Returns or creates an asyncio.Lock bound to the current event loop."""
    global _lock, _lock_loop
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def get_shared_client() -> httpx.AsyncClient:
    """
    Returns the persistent, loop-bound httpx.AsyncClient singleton.
    Configured with HTTP/2 support, connection pooling limits (50 keepalive, 100 max),
    and a default 30.0s timeout.

    If the current event loop has changed or the client has been closed,
    safely re-initializes a new client instance.
    """
    global _shared_client, _client_loop

    current_loop = asyncio.get_running_loop()

    # Fast path: client exists, is open, and is bound to current loop
    if (
        _shared_client is not None
        and not _shared_client.is_closed
        and _client_loop is current_loop
    ):
        return _shared_client

    lock = _get_lock(current_loop)
    async with lock:
        # Re-check under lock
        if (
            _shared_client is not None
            and not _shared_client.is_closed
            and _client_loop is current_loop
        ):
            return _shared_client

        # If previous client was bound to an old loop or closed, clean up reference
        if _shared_client is not None:
            if not _shared_client.is_closed:
                if _client_loop is current_loop:
                    try:
                        await _shared_client.aclose()
                    except Exception as exc:
                        logger.debug(f"Error closing previous client during re-init: {exc}")
                elif _client_loop is not None and _client_loop.is_running():
                    try:
                        asyncio.run_coroutine_threadsafe(_shared_client.aclose(), _client_loop)
                    except Exception:
                        pass
            _shared_client = None

        try:
            from makima.config import get_settings
            s = get_settings()
            max_keepalive = getattr(s, "http_max_keepalive", 50)
            max_conn = getattr(s, "http_max_connections", 100)
            timeout_val = getattr(s, "http_timeout", 30.0)
        except Exception:
            max_keepalive = 50
            max_conn = 100
            timeout_val = 30.0

        logger.debug(
            "Initializing persistent shared httpx.AsyncClient (max_conn=%d, keepalive=%d, timeout=%.1fs)",
            max_conn, max_keepalive, timeout_val
        )
        _shared_client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(
                max_keepalive_connections=max_keepalive,
                max_connections=max_conn,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(timeout_val, connect=5.0),
        )
        _client_loop = current_loop
        return _shared_client


async def close_shared_client() -> None:
    """
    Gracefully drains and closes the shared persistent HTTP client pool.
    Safe to call multiple times.
    """
    global _shared_client, _client_loop
    if _shared_client is not None:
        try:
            if not _shared_client.is_closed:
                await _shared_client.aclose()
        except Exception as exc:
            logger.debug(f"Error closing shared HTTP client: {exc}")
        finally:
            _shared_client = None
            _client_loop = None


def get_shared_sync_client() -> httpx.Client:
    """
    Returns a persistent, thread-safe synchronous httpx.Client with connection pooling.
    Used by background worker threads to avoid socket exhaustion and TLS re-handshakes.
    """
    global _shared_sync_client
    if _shared_sync_client is not None and not _shared_sync_client.is_closed:
        return _shared_sync_client

    with _sync_lock:
        if _shared_sync_client is None or _shared_sync_client.is_closed:
            try:
                from makima.config import get_settings
                s = get_settings()
                max_keepalive = getattr(s, "http_max_keepalive", 20)
                max_conn = getattr(s, "http_max_connections", 50)
                timeout_val = getattr(s, "http_timeout", 30.0)
            except Exception:
                max_keepalive = 20
                max_conn = 50
                timeout_val = 30.0

            _shared_sync_client = httpx.Client(
                http2=True,
                limits=httpx.Limits(
                    max_keepalive_connections=max_keepalive,
                    max_connections=max_conn,
                    keepalive_expiry=30.0,
                ),
                timeout=httpx.Timeout(timeout_val, connect=5.0),
            )
    return _shared_sync_client


def close_shared_sync_client() -> None:
    """Closes the synchronous HTTP client pool."""
    global _shared_sync_client
    with _sync_lock:
        if _shared_sync_client is not None:
            try:
                if not _shared_sync_client.is_closed:
                    _shared_sync_client.close()
            except Exception as exc:
                logger.debug(f"Error closing shared sync HTTP client: {exc}")
            finally:
                _shared_sync_client = None


class HTTPPool:
    """
    Class-based interface providing thread-safe and loop-safe access to the shared HTTP pool.
    """

    @classmethod
    async def get_client(cls) -> httpx.AsyncClient:
        """Returns the loop-aware persistent httpx.AsyncClient singleton."""
        return await get_shared_client()

    @classmethod
    async def close(cls) -> None:
        """Closes the active connection pool gracefully."""
        await close_shared_client()

    @classmethod
    def get_sync_client(cls) -> httpx.Client:
        """Returns the persistent synchronous httpx.Client singleton."""
        return get_shared_sync_client()

    @classmethod
    def close_sync(cls) -> None:
        """Closes the synchronous HTTP client pool."""
        close_shared_sync_client()
