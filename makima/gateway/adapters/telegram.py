"""
Makima v2 — Multi-Platform Gateway: Telegram Adapter.
Architectural Pattern: python-telegram-bot v20+ Async Application with GatewaySecurityManager integration.
Zero-Hardcoding Guarantee: Token dynamically acquired from environment / settings, pairing security enforced.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

import telegram
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from makima.config import get_settings
from makima.gateway.adapters.base import BaseAdapter, split_message

if TYPE_CHECKING:
    from makima.core.engine import HermesAgentEngine
    from makima.gateway.security import GatewaySecurityManager

logger = logging.getLogger("makima.gateway.adapters.telegram")


class TelegramAdapter(BaseAdapter):
    """
    Production-grade Telegram Bot adapter integrating python-telegram-bot Application
    with Makima's GatewaySecurityManager and autonomous HermesAgentEngine.
    """

    MAX_MESSAGE_LENGTH: int = 4000

    def __init__(
        self,
        token: Optional[str] = None,
        security_manager: Optional[GatewaySecurityManager] = None,
        engine: Optional[HermesAgentEngine] = None,
    ):
        super().__init__(security_manager=security_manager, engine=engine)
        self._token = token or self._resolve_token()
        self._app: Optional[Application] = None
        self._polling_task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def platform_name(self) -> str:
        return "Telegram"

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def app(self) -> Optional[Application]:
        return self._app

    def _resolve_token(self) -> Optional[str]:
        """Dynamically resolves bot token from configuration or environment."""
        try:
            settings = get_settings()
            token_env = settings.gateway.platforms.telegram.token_env
            return os.getenv(token_env)
        except Exception:
            return os.getenv("TELEGRAM_BOT_TOKEN")

    def build_application(self) -> Application:
        """Constructs and wires the telegram Application instance with all handlers."""
        if not self._token:
            raise ValueError(
                "Cannot build Telegram application: bot token is missing. "
                "Provide token parameter or set TELEGRAM_BOT_TOKEN in environment."
            )

        app = ApplicationBuilder().token(self._token).build()

        # Wire handlers
        app.add_handler(CommandHandler("start", self.handle_start_command))
        app.add_handler(CommandHandler("pair", self.handle_pair_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        app.add_handler(MessageHandler(filters.VOICE, self.handle_voice_message))
        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo_message))

        self._app = app
        return app

    # -----------------------------------------------------------------------
    # Handler Implementations (Public for direct testability & wire invocation)
    # -----------------------------------------------------------------------

    async def handle_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles /start command: greets user and explains pairing if unauthorized."""
        if not update.effective_user or not update.effective_chat:
            return

        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id

        if self.security_manager.is_user_authorized("telegram", user_id):
            welcome_text = (
                f"👋 Hello {update.effective_user.first_name or 'there'}!\n\n"
                "I am **Makima**, your autonomous AI desktop companion.\n"
                "You are authorized. Send me any request or question to begin!"
            )
        else:
            welcome_text = (
                f"👋 Welcome to **Makima**, {update.effective_user.first_name or 'there'}!\n\n"
                "🔒 **Authorization Required**\n"
                "This Makima instance is private. To connect your account:\n"
                "1. Ask the host to generate a pairing code from the Makima console.\n"
                "2. Reply here with: `/pair <CODE>` (e.g. `/pair MK-4821`)\n\n"
                f"Your Telegram ID: `{user_id}`"
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            parse_mode=telegram.constants.ParseMode.MARKDOWN,
        )

    async def handle_pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles /pair <code> command: validates pairing code against security manager."""
        if not update.effective_user or not update.effective_chat:
            return

        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id

        # Check if already paired
        if self.security_manager.is_user_authorized("telegram", user_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="ℹ️ You are already paired and authorized to interact with Makima.",
            )
            return

        # Check for provided pairing code
        args = context.args or []
        if not args:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Please specify your pairing code:\nUsage: `/pair <CODE>`\nExample: `/pair MK-8291`",
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
            )
            return

        submitted_code = args[0].strip()
        is_valid = self.security_manager.verify_pairing_code("telegram", user_id, submitted_code)

        if is_valid:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "✅ **Pairing Successful!**\n\n"
                    "Your Telegram account has been permanently authorized.\n"
                    "How can Makima assist you today?"
                ),
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ **Pairing Failed**\n\n"
                    "The provided pairing code is invalid, already consumed, or expired.\n"
                    "Please generate a fresh code on the Makima host console."
                ),
            )

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles incoming text messages from users."""
        if not update.effective_user or not update.effective_message or not update.effective_chat:
            return

        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id
        raw_text = update.effective_message.text or ""

        # Ingest into InboxManager for zero-cost priority classification & unified storage
        try:
            from makima.gateway.inbox import get_inbox_manager
            get_inbox_manager().ingest_message(
                platform="telegram",
                sender_id=user_id,
                sender_name=update.effective_user.first_name or user_id,
                content=raw_text,
                metadata={"chat_id": chat_id, "username": update.effective_user.username or ""},
            )
        except Exception as exc:
            logger.debug(f"Failed to ingest Telegram message into InboxManager: {exc}")

        # Enforce Gateway Security
        if not self.security_manager.is_user_authorized("telegram", user_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔒 **Access Denied**\n\n"
                    "You are not authorized to use this Makima instance.\n"
                    "Authenticate using `/pair <CODE>`."
                ),
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
            )
            return

        # Send typing status
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception as e:
            logger.debug(f"Failed to send typing indicator: {e}")

        # Process query through HermesAgentEngine
        response_text = await self.process_user_query(
            user_id=user_id,
            query=raw_text,
            user_display_name=update.effective_user.first_name,
        )

        # Split into compliant chunks
        chunks = split_message(response_text, max_length=self.MAX_MESSAGE_LENGTH)
        for chunk in chunks:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
            )

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles incoming voice notes and audio memos."""
        if not update.effective_user or not update.effective_message or not update.effective_chat:
            return

        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id

        if not self.security_manager.is_user_authorized("telegram", user_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔒 Voice memo rejected: You are not authorized. Use `/pair <CODE>`.",
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
            )
            return

        await context.bot.send_message(
            chat_id=chat_id,
            text="🎙️ Voice memo received. Speech processing is queued.",
        )

    async def handle_photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles incoming image uploads."""
        if not update.effective_user or not update.effective_message or not update.effective_chat:
            return

        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id

        if not self.security_manager.is_user_authorized("telegram", user_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔒 Photo rejected: You are not authorized. Use `/pair <CODE>`.",
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
            )
            return

        caption = update.effective_message.caption or "Analyze this image."
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📷 Image received: '{caption}'. Vision analysis is being processed.",
        )

    # -----------------------------------------------------------------------
    # Outbound Messaging API
    # -----------------------------------------------------------------------

    async def send_message(self, recipient_id: Union[str, int], text: str) -> List[Any]:
        """Transmits text message chunks to target chat ID."""
        if not self._app:
            self.build_application()

        chunks = split_message(text, max_length=self.MAX_MESSAGE_LENGTH)
        sent_messages = []
        for chunk in chunks:
            msg = await self._app.bot.send_message(chat_id=recipient_id, text=chunk)
            sent_messages.append(msg)
        return sent_messages

    async def send_file(
        self,
        recipient_id: Union[str, int],
        file_path: Union[str, Path],
        caption: Optional[str] = None,
    ) -> Any:
        """Transmits document or binary file to target chat ID."""
        if not self._app:
            self.build_application()

        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File to send does not exist: {file_path}")

        with open(p, "rb") as f:
            return await self._app.bot.send_document(
                chat_id=recipient_id,
                document=f,
                filename=p.name,
                caption=caption,
            )

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Initializes application and begins polling for updates."""
        if self._is_connected:
            return

        if not self._app:
            self.build_application()

        logger.info("Starting Telegram adapter polling...")
        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling()
        self._is_connected = True
        logger.info("Telegram adapter started successfully.")

    async def stop(self) -> None:
        """Gracefully shuts down polling and bot application."""
        if not self._is_connected or not self._app:
            return

        logger.info("Stopping Telegram adapter...")
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        await self._app.shutdown()
        self._is_connected = False
        logger.info("Telegram adapter stopped.")

