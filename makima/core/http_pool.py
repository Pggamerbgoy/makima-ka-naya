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
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Module-level singleton state
_shared_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None
_lock: Optional[asyncio.Lock] = None
_lock_loop: Optional[asyncio.AbstractEventLoop] = None


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
            if not _shared_client.is_closed and _client_loop is current_loop:
                try:
                    await _shared_client.aclose()
                except Exception as exc:
                    logger.debug(f"Error closing previous client during re-init: {exc}")
            _shared_client = None

        logger.debug("Initializing persistent shared httpx.AsyncClient singleton.")
        _shared_client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(
                max_keepalive_connections=50,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(30.0, connect=5.0),
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
