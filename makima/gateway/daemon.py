"""
Makima v2 — Master Gateway Daemon Core.
Architectural Pattern: Multi-Platform Adapter Supervisor & Async Lifecycle Runner.
Zero-Hardcoding Guarantee: Fully dynamic adapter auto-registration, graceful signal handling, and clean shutdown.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
from typing import Any, Dict, Optional

from makima.config import MakimaSettings, get_settings
from makima.gateway.scheduler import GatewayScheduler
from makima.gateway.security import GatewaySecurityManager

logger = logging.getLogger("makima.gateway.daemon")


class GatewayDaemon:
    """
    Master daemon supervisor for Makima Gateway.
    Coordinates:
      1. Security & pairing authorization manager.
      2. Background cron & reminder scheduler.
      3. Multi-platform messaging adapters (Telegram, Discord, WhatsApp).
      4. Graceful async lifecycle and OS shutdown signals.
    """

    def __init__(
        self,
        settings: Optional[MakimaSettings] = None,
        security_manager: Optional[GatewaySecurityManager] = None,
        scheduler: Optional[GatewayScheduler] = None,
        engine: Optional[Any] = None,
    ):
        self.settings = settings or get_settings()
        self.security = security_manager or GatewaySecurityManager()
        self.scheduler = scheduler or GatewayScheduler()
        self.engine = engine

        self._adapters: Dict[str, Any] = {}
        self._is_running = False
        self._shutdown_event = asyncio.Event()
        self._signal_handlers_registered = False

    @property
    def is_running(self) -> bool:
        """Returns True if the daemon is currently active and running."""
        return self._is_running

    @property
    def adapters(self) -> Dict[str, Any]:
        """Dictionary of registered platform adapters."""
        return dict(self._adapters)

    def register_adapter(self, name: str, adapter: Any) -> None:
        """
        Registers a communication platform adapter with the gateway daemon.
        Adapter should implement optional async start() and stop() methods.
        """
        adapter_name = name.lower().strip()
        # A daemon owns the security boundary and runtime. Adapters must share
        # both instances so pairing and session continuity work consistently.
        if self.engine is not None and getattr(adapter, "_engine", None) is None:
            adapter._engine = self.engine
        if getattr(adapter, "_security_manager", None) is None:
            adapter._security_manager = self.security
        self._adapters[adapter_name] = adapter
        logger.info(f"Registered gateway adapter: '{adapter_name}' ({type(adapter).__name__})")

    def unregister_adapter(self, name: str) -> Optional[Any]:
        """Removes a registered adapter from the daemon."""
        return self._adapters.pop(name.lower().strip(), None)

    def get_adapter(self, name: str) -> Optional[Any]:
        """Retrieves a registered platform adapter by name."""
        return self._adapters.get(name.lower().strip())

    def _setup_signals(self) -> None:
        """Configures OS termination signals (SIGINT, SIGTERM) for graceful shutdown."""
        if self._signal_handlers_registered:
            return

        def _handle_signal(sig, frame=None):
            logger.info(f"Received termination signal {sig}. Initiating graceful shutdown...")
            self._shutdown_event.set()

        try:
            # Check if running in main thread
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
            self._signal_handlers_registered = True
            logger.debug("Registered OS signal handlers for graceful shutdown.")
        except (ValueError, AttributeError) as e:
            logger.debug(f"Could not register signal handlers (e.g. non-main thread): {e}")

    async def start(self) -> None:
        """
        Starts the gateway daemon, scheduler, and all registered adapters.
        """
        if self._is_running:
            logger.warning("GatewayDaemon is already running.")
            return

        logger.info("Starting Makima Gateway Daemon...")
        self._shutdown_event.clear()
        self._setup_signals()

        # 1. Start job scheduler
        self.scheduler.start()

        # 2. Check if initial pairing code is needed
        if self.security.pairing_code_enabled and not self.security.allow_all_users:
            authorized = self.security.list_authorized_users()
            allowlist = self.security.allowlist_user_ids
            if not authorized and not allowlist:
                # Generate pairing code so the owner can connect on startup
                code = self.security.generate_pairing_code()
                logger.info(f"Initial gateway pairing code generated: {code}")

        # 3. Start registered adapters
        for name, adapter in self._adapters.items():
            if hasattr(adapter, "start") and callable(adapter.start):
                logger.info(f"Starting adapter '{name}'...")
                try:
                    res = adapter.start()
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    logger.error(f"Error starting adapter '{name}': {e}", exc_info=True)

        self._is_running = True
        logger.info("Makima Gateway Daemon running successfully.")

    async def stop(self) -> None:
        """
        Gracefully stops all registered adapters, stops scheduler, and releases resources.
        """
        if not self._is_running:
            return

        logger.info("Stopping Makima Gateway Daemon...")

        # 1. Stop all registered adapters in reverse order
        for name, adapter in reversed(list(self._adapters.items())):
            if hasattr(adapter, "stop") and callable(adapter.stop):
                logger.info(f"Stopping adapter '{name}'...")
                try:
                    res = adapter.stop()
                    if inspect.isawaitable(res):
                        await res
                except Exception as e:
                    logger.error(f"Error stopping adapter '{name}': {e}", exc_info=True)

        # 2. Stop scheduler
        try:
            self.scheduler.shutdown(wait=False)
            await asyncio.sleep(0.01)
        except Exception as e:
            logger.warning(f"Error during scheduler shutdown: {e}")

        self._is_running = False
        self._shutdown_event.set()
        logger.info("Makima Gateway Daemon stopped cleanly.")

    async def run_forever(self) -> None:
        """
        Runs the gateway daemon until an external cancellation signal or stop() is requested.
        """
        await self.start()
        try:
            await self._shutdown_event.wait()
        finally:
            await self.stop()
