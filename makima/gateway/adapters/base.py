"""
Makima v2 — Multi-Platform Gateway: Base Adapter Interface.
Architectural Pattern: Abstract Base Class defining universal messaging adapter lifecycle.
Zero-Hardcoding Guarantee: Decoupled from transport specifics, token sources, and platform protocols.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

if TYPE_CHECKING:
    from makima.core.engine import HermesAgentEngine
    from makima.gateway.security import GatewaySecurityManager

logger = logging.getLogger("makima.gateway.adapters.base")


def split_message(text: str, max_length: int = 2000) -> List[str]:
    """
    Intelligently splits a message string into chunks adhering to platform length limits
    (e.g. 2000 chars for Discord, 4096 chars for Telegram).
    Splits preferentially at paragraph breaks, line breaks, spaces, or hard boundaries.
    """
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = -1

        # 1. Try double newline (paragraph boundary)
        p_idx = remaining.rfind("\n\n", 0, max_length)
        if p_idx != -1 and p_idx >= max_length // 2:
            split_pos = p_idx + 2

        # 2. Try single newline
        if split_pos == -1:
            n_idx = remaining.rfind("\n", 0, max_length)
            if n_idx != -1 and n_idx >= max_length // 2:
                split_pos = n_idx + 1

        # 3. Try space boundary
        if split_pos == -1:
            s_idx = remaining.rfind(" ", 0, max_length)
            if s_idx != -1 and s_idx >= max_length // 2:
                split_pos = s_idx + 1

        # 4. Fallback to hard split
        if split_pos == -1:
            split_pos = max_length

        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks


class BaseAdapter(ABC):
    """
    Universal abstract base class for external messaging platform adapters (Telegram, Discord, etc.).
    """

    def __init__(
        self,
        security_manager: Optional[GatewaySecurityManager] = None,
        engine: Optional[HermesAgentEngine] = None,
    ):
        self._security_manager = security_manager
        self._engine = engine
        self._is_connected: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Internal identifier for this adapter (e.g. 'telegram', 'discord')."""
        pass

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name (e.g. 'Telegram', 'Discord')."""
        pass

    @property
    def is_connected(self) -> bool:
        """Whether the adapter is actively connected and servicing requests."""
        return self._is_connected

    @property
    def security_manager(self) -> GatewaySecurityManager:
        """Lazy-loaded or injected GatewaySecurityManager instance."""
        if self._security_manager is None:
            from makima.gateway.security import GatewaySecurityManager
            self._security_manager = GatewaySecurityManager()
        return self._security_manager

    @property
    def engine(self) -> HermesAgentEngine:
        """Lazy-loaded or injected HermesAgentEngine instance."""
        if self._engine is None:
            from makima.runtime import build_engine
            self._engine = build_engine()
        return self._engine

    @abstractmethod
    async def start(self) -> None:
        """Starts the adapter connection and event listening loop."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully halts the adapter connection."""
        pass

    @abstractmethod
    async def send_message(
        self,
        recipient_id: Union[str, int],
        text: str,
    ) -> Any:
        """
        Sends a text message to a user or channel.

        Args:
            recipient_id: Platform-specific recipient identifier.
            text: Text content to transmit.
        """
        pass

    @abstractmethod
    async def send_file(
        self,
        recipient_id: Union[str, int],
        file_path: Union[str, Path],
        caption: Optional[str] = None,
    ) -> Any:
        """
        Transmits a document, image, or file payload to a recipient.

        Args:
            recipient_id: Platform-specific recipient identifier.
            file_path: Path to target file on disk.
            caption: Optional text caption accompanying the file.
        """
        pass

    async def process_user_query(
        self,
        user_id: Union[str, int],
        query: str,
        user_display_name: Optional[str] = None,
    ) -> str:
        """
        Dispatches a user's authorized message into the Hermes agent engine
        and returns the engine's final response content.
        """
        try:
            from makima.runtime import build_registry
            from makima.tools.registry import CapabilityToolRegistry
            reg = CapabilityToolRegistry(build_registry(), profile="chat")
            result = await self.engine.run(
                prompt=query,
                tools=reg,
                tool_executor=reg.execute,
                session_id=f"gateway:{self.name}:{str(user_id)[:160]}",
            )
            return result.content
        except Exception as exc:
            logger.error(f"Engine execution error for {self.name}:{user_id}: {exc}", exc_info=True)
            return f"⚠️ Error processing request: {type(exc).__name__}: {str(exc)}"
