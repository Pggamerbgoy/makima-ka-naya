"""
Makima v2 — Multi-Platform Gateway: Discord Adapter.
Architectural Pattern: discord.py Async Client with GatewaySecurityManager authorization.
Zero-Hardcoding Guarantee: Token dynamically acquired from environment / settings, author security enforced.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

import discord

from makima.config import get_settings
from makima.gateway.adapters.base import BaseAdapter, split_message

if TYPE_CHECKING:
    from makima.core.engine import HermesAgentEngine
    from makima.gateway.security import GatewaySecurityManager

logger = logging.getLogger("makima.gateway.adapters.discord")


class DiscordAdapter(BaseAdapter):
    """
    Production-grade Discord adapter using discord.py Client with GatewaySecurityManager
    and autonomous HermesAgentEngine dispatching.
    """

    MAX_MESSAGE_LENGTH: int = 1950  # Leave room below Discord's 2000 char ceiling

    def __init__(
        self,
        token: Optional[str] = None,
        security_manager: Optional[GatewaySecurityManager] = None,
        engine: Optional[HermesAgentEngine] = None,
        intents: Optional[discord.Intents] = None,
    ):
        super().__init__(security_manager=security_manager, engine=engine)
        self._token = token or self._resolve_token()
        self._intents = intents or self._default_intents()
        self._client: Optional[discord.Client] = None
        self._bot_task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return "discord"

    @property
    def platform_name(self) -> str:
        return "Discord"

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def client(self) -> Optional[discord.Client]:
        return self._client

    def _default_intents(self) -> discord.Intents:
        """Configures required intents including message content reading."""
        intents = discord.Intents.default()
        intents.message_content = True
        return intents

    def _resolve_token(self) -> Optional[str]:
        """Dynamically resolves Discord bot token from settings or environment."""
        try:
            settings = get_settings()
            token_env = settings.gateway.platforms.discord.token_env
            return os.getenv(token_env)
        except Exception:
            return os.getenv("DISCORD_BOT_TOKEN")

    def build_client(self) -> discord.Client:
        """Constructs and wires the discord.Client with event handlers."""
        client = discord.Client(intents=self._intents)

        @client.event
        async def on_ready():
            self._is_connected = True
            logger.info(f"Discord bot logged in as {client.user} (ID: {client.user.id if client.user else 'unknown'})")

        @client.event
        async def on_message(message: discord.Message):
            await self.handle_message(message)

        self._client = client
        return client

    # -----------------------------------------------------------------------
    # Message Dispatcher & Handlers (Public for direct testing & mock feeds)
    # -----------------------------------------------------------------------

    async def handle_message(self, message: discord.Message) -> None:
        """
        Dispatches incoming Discord messages based on authorization, mentions, and DMs.
        """
        # Ignore messages from self or other bots
        if message.author.bot:
            return
        if self._client and self._client.user and message.author.id == self._client.user.id:
            return

        user_id = str(message.author.id)
        raw_content = message.content.strip() if message.content else ""

        # 1. Handle Pairing Command (!pair <code> or /pair <code>)
        if raw_content.startswith(("!pair", "/pair")):
            await self.handle_pairing_command(message, raw_content)
            return

        # 2. Check if bot should respond (DM, mention, or thread)
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = False
        if self._client and self._client.user:
            bot_id = self._client.user.id
            if any(getattr(m, "id", None) == bot_id for m in message.mentions):
                is_mentioned = True
            elif f"<@{bot_id}>" in raw_content or f"<@!{bot_id}>" in raw_content:
                is_mentioned = True

        # In guild channels, only respond if directly mentioned (unless DM)
        if not is_dm and not is_mentioned:
            return

        # 3. Security Authorization Verification
        if not self.security_manager.is_user_authorized("discord", user_id):
            await message.reply(
                "🔒 **Authorization Required**\n\n"
                "This Makima instance is private. To connect your account:\n"
                "1. Ask the host to generate a pairing code from the Makima console.\n"
                "2. Reply with: `!pair <CODE>` (e.g. `!pair MK-9421`)\n\n"
                f"Your Discord ID: `{user_id}`"
            )
            return

        # 4. Clean Prompt Content (Strip bot mention tag)
        clean_text = raw_content
        if self._client and self._client.user:
            clean_text = re.sub(rf"<@!?{self._client.user.id}>", "", clean_text).strip()

        # Ingest into InboxManager for zero-cost priority classification & unified storage
        try:
            from makima.gateway.inbox import get_inbox_manager
            get_inbox_manager().ingest_message(
                platform="discord",
                sender_id=user_id,
                sender_name=getattr(message.author, "display_name", None) or getattr(message.author, "name", str(user_id)),
                content=clean_text or raw_content,
                metadata={
                    "channel_id": getattr(message.channel, "id", None),
                    "is_dm": is_dm,
                    "is_mentioned": is_mentioned,
                },
            )
        except Exception as exc:
            logger.debug(f"Failed to ingest Discord message into InboxManager: {exc}")

        if not clean_text:
            await message.reply("Hello! How can Makima assist you today?")
            return

        # 5. Process through HermesAgentEngine with typing indicator
        async with message.channel.typing():
            response_text = await self.process_user_query(
                user_id=user_id,
                query=clean_text,
                user_display_name=message.author.display_name,
            )

        # 6. Send Response Chunks ( Adhere to Discord 2000 char limit )
        chunks = split_message(response_text, max_length=self.MAX_MESSAGE_LENGTH)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)

    async def handle_pairing_command(self, message: discord.Message, raw_content: str) -> None:
        """Validates pairing code submitted by Discord user."""
        user_id = str(message.author.id)

        # Check if already paired
        if self.security_manager.is_user_authorized("discord", user_id):
            await message.reply("ℹ️ Your Discord account is already authorized to use Makima.")
            return

        parts = raw_content.split()
        if len(parts) < 2:
            await message.reply(
                "⚠️ Please provide your pairing code.\n"
                "Usage: `!pair <CODE>`\n"
                "Example: `!pair MK-8291`"
            )
            return

        submitted_code = parts[1].strip()
        is_valid = self.security_manager.verify_pairing_code("discord", user_id, submitted_code)

        if is_valid:
            await message.reply(
                "✅ **Pairing Successful!**\n\n"
                "Your Discord account has been authorized. You can now mention me in channels or DM me anytime!"
            )
        else:
            await message.reply(
                "❌ **Pairing Failed**\n\n"
                "The provided code is invalid, already consumed, or expired.\n"
                "Please request a fresh code on the host console."
            )

    # -----------------------------------------------------------------------
    # Outbound Messaging API
    # -----------------------------------------------------------------------

    async def send_message(self, recipient_id: Union[str, int], text: str) -> List[Any]:
        """Transmits chunked text messages to a Discord user or channel ID."""
        if not self._client:
            self.build_client()

        target = None
        rid = int(recipient_id)

        # Try to resolve channel first, then user
        try:
            target = self._client.get_channel(rid) or await self._client.fetch_channel(rid)
        except Exception:
            try:
                target = self._client.get_user(rid) or await self._client.fetch_user(rid)
            except Exception as e:
                logger.error(f"Failed to resolve Discord recipient {recipient_id}: {e}")
                raise ValueError(f"Could not locate Discord channel or user ID: {recipient_id}") from e

        chunks = split_message(text, max_length=self.MAX_MESSAGE_LENGTH)
        sent = []
        for chunk in chunks:
            msg = await target.send(chunk)
            sent.append(msg)
        return sent

    async def send_file(
        self,
        recipient_id: Union[str, int],
        file_path: Union[str, Path],
        caption: Optional[str] = None,
    ) -> Any:
        """Transmits a file to a Discord user or channel."""
        if not self._client:
            self.build_client()

        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File to send does not exist: {file_path}")

        target = None
        rid = int(recipient_id)

        try:
            target = self._client.get_channel(rid) or await self._client.fetch_channel(rid)
        except Exception:
            target = self._client.get_user(rid) or await self._client.fetch_user(rid)

        dfile = discord.File(str(p), filename=p.name)
        return await target.send(content=caption, file=dfile)

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Connects the Discord client in a background asyncio task."""
        if self._is_connected:
            return

        if not self._token:
            raise ValueError(
                "Cannot start Discord adapter: bot token is missing. "
                "Provide token parameter or set DISCORD_BOT_TOKEN in environment."
            )

        if not self._client:
            self.build_client()

        logger.info("Starting Discord adapter...")
        self._bot_task = asyncio.create_task(self._client.start(self._token))

        # Wait briefly for connection or ready event
        try:
            await asyncio.wait_for(self._client.wait_until_ready(), timeout=10.0)
            self._is_connected = True
            logger.info("Discord adapter started and ready.")
        except asyncio.TimeoutError:
            logger.warning("Discord client start timed out waiting for ready state.")

    async def stop(self) -> None:
        """Gracefully closes Discord client and background tasks."""
        if self._client and not self._client.is_closed():
            logger.info("Closing Discord adapter client...")
            await self._client.close()

        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass

        self._is_connected = False
        logger.info("Discord adapter stopped.")

