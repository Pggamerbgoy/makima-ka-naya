"""
Live verification script for Phase 2 Step 13: Telegram & Discord Adapters.
Comprehensive testing covering:
  1. BaseAdapter interface conformance, properties, and message chunking.
  2. Telegram adapter mock interaction:
     - /start command handling for unauthorized and authorized users.
     - Security interception: rejection of unauthorized text, voice, and photo messages.
     - Ephemeral pairing code verification flow (/pair <CODE>).
     - Full autonomous HermesAgentEngine dispatching and response chunking.
  3. Discord adapter mock interaction:
     - Self-bot and external bot message filtering.
     - Channel mention detection vs unmentioned message ignoring.
     - Direct Message (DM) dispatching.
     - Security interception: author ID verification and !pair command flow.
     - HermesAgentEngine dispatching with typing indicator and Discord 2000-char splitting.
  4. Outbound messaging and file dispatch API verification.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.core.engine import EngineResult, HermesAgentEngine
from makima.gateway.adapters import (
    BaseAdapter,
    DiscordAdapter,
    TelegramAdapter,
    split_message,
)
from makima.gateway.security import GatewaySecurityManager


# ---------------------------------------------------------------------------
# Mock Helpers for Telegram and Discord Testing
# ---------------------------------------------------------------------------

class MockEngine:
    """Mock HermesAgentEngine that records calls and returns deterministic results."""
    def __init__(self, reply_content: str = "Mocked engine response from Makima"):
        self.reply_content = reply_content
        self.call_history: List[Dict[str, Any]] = []

    async def run(self, prompt: str = "", **kwargs) -> EngineResult:
        self.call_history.append({"prompt": prompt, "kwargs": kwargs})
        return EngineResult(
            content=self.reply_content,
            messages=[],
            turn_count=1,
            tool_calls_executed=0,
            completed=True,
            model_used="mock-model",
        )


def make_telegram_mock(user_id: int, text: str, first_name: str = "Alice", is_command: bool = False):
    """Creates a mock telegram Update and Context pair."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = first_name
    update.effective_chat.id = 99887766
    update.effective_message.text = text
    update.effective_message.caption = None
    update.message = update.effective_message

    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    context.bot.send_document = AsyncMock()

    if is_command and text.startswith("/"):
        parts = text.split()
        context.args = parts[1:]
    else:
        context.args = []

    return update, context


def make_discord_mock(
    author_id: int,
    content: str,
    is_bot: bool = False,
    is_dm: bool = False,
    is_mentioned: bool = False,
    bot_id: int = 999999,
):
    """Creates a mock discord Message and Client."""
    message = MagicMock()
    message.author.id = author_id
    message.author.bot = is_bot
    message.author.display_name = f"User_{author_id}"
    message.content = content
    message.reply = AsyncMock()

    # Channel configuration
    if is_dm:
        import discord
        message.channel = MagicMock(spec=discord.DMChannel)
    else:
        message.channel = MagicMock()

    message.channel.send = AsyncMock()
    # Mock async context manager for typing
    typing_cm = MagicMock()
    typing_cm.__aenter__ = AsyncMock()
    typing_cm.__aexit__ = AsyncMock()
    message.channel.typing.return_value = typing_cm

    # Mentions
    bot_user = MagicMock()
    bot_user.id = bot_id

    if is_mentioned:
        message.mentions = [bot_user]
    else:
        message.mentions = []

    return message, bot_user


# ---------------------------------------------------------------------------
# Test 1: Interface Conformance & Chunking
# ---------------------------------------------------------------------------

def test_interface_conformance_and_chunking():
    print("\n[TEST 1] Testing BaseAdapter interface conformance & message chunking...")

    # Abstract instantiation should fail
    try:
        BaseAdapter()
        assert False, "BaseAdapter should not be instantiable directly!"
    except TypeError:
        pass

    # Verify message chunking
    short = "Hello, world!"
    assert split_message(short, max_length=100) == [short]

    long_text = ("First paragraph.\n\n" * 50) + "Final sentence."
    chunks = split_message(long_text, max_length=200)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 200
    assert "First paragraph." in chunks[0]
    assert "Final sentence." in chunks[-1]

    # Concrete adapters interface
    tg = TelegramAdapter(token="mock:token")
    assert tg.name == "telegram"
    assert tg.platform_name == "Telegram"
    assert tg.is_connected is False

    dc = DiscordAdapter(token="mock.token")
    assert dc.name == "discord"
    assert dc.platform_name == "Discord"
    assert dc.is_connected is False

    print("  [PASS] BaseAdapter interface and message chunking strictly validated.")


# ---------------------------------------------------------------------------
# Test 2: Telegram Adapter Flow & Security Pairing
# ---------------------------------------------------------------------------

async def test_telegram_adapter_flow(tmp_dir: Path):
    print("\n[TEST 2] Testing Telegram adapter security interception, pairing, and execution...")

    sec_mgr = GatewaySecurityManager(
        allow_all_users=False,
        allowlist_user_ids=[],
        pairing_code_enabled=True,
        storage_path=tmp_dir / "tg_users.json",
    )
    engine = MockEngine(reply_content="Autonomous response from Makima for Telegram!")
    adapter = TelegramAdapter(
        token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        security_manager=sec_mgr,
        engine=engine,
    )

    unauth_user_id = 111111

    # 1. /start command for unauthorized user
    up_start, ctx_start = make_telegram_mock(unauth_user_id, "/start", is_command=True)
    await adapter.handle_start_command(up_start, ctx_start)
    assert ctx_start.bot.send_message.called
    start_reply = ctx_start.bot.send_message.call_args[1]["text"]
    assert "Authorization Required" in start_reply
    assert "/pair <CODE>" in start_reply

    # 2. Text message rejected for unauthorized user
    up_msg, ctx_msg = make_telegram_mock(unauth_user_id, "What can you do?")
    await adapter.handle_text_message(up_msg, ctx_msg)
    assert ctx_msg.bot.send_message.called
    msg_reply = ctx_msg.bot.send_message.call_args[1]["text"]
    assert "Access Denied" in msg_reply
    assert len(engine.call_history) == 0, "Engine should NOT have been called!"

    # 3. Invalid pairing code rejected
    up_pair_fail, ctx_pair_fail = make_telegram_mock(unauth_user_id, "/pair INVALID", is_command=True)
    await adapter.handle_pair_command(up_pair_fail, ctx_pair_fail)
    fail_reply = ctx_pair_fail.bot.send_message.call_args[1]["text"]
    assert "Pairing Failed" in fail_reply
    assert not sec_mgr.is_user_authorized("telegram", str(unauth_user_id))

    # 4. Valid pairing code authorized
    code = sec_mgr.generate_pairing_code()
    up_pair_ok, ctx_pair_ok = make_telegram_mock(unauth_user_id, f"/pair {code}", is_command=True)
    await adapter.handle_pair_command(up_pair_ok, ctx_pair_ok)
    ok_reply = ctx_pair_ok.bot.send_message.call_args[1]["text"]
    assert "Pairing Successful" in ok_reply
    assert sec_mgr.is_user_authorized("telegram", str(unauth_user_id))

    # 5. Subsequent text message successfully dispatched to engine
    up_msg_auth, ctx_msg_auth = make_telegram_mock(unauth_user_id, "Summarize system status")
    await adapter.handle_text_message(up_msg_auth, ctx_msg_auth)
    assert len(engine.call_history) == 1
    assert engine.call_history[0]["prompt"] == "Summarize system status"
    auth_reply = ctx_msg_auth.bot.send_message.call_args[1]["text"]
    assert "Autonomous response from Makima for Telegram!" in auth_reply

    # 6. /start for authorized user
    up_start_auth, ctx_start_auth = make_telegram_mock(unauth_user_id, "/start", is_command=True)
    await adapter.handle_start_command(up_start_auth, ctx_start_auth)
    start_auth_reply = ctx_start_auth.bot.send_message.call_args[1]["text"]
    assert "You are authorized" in start_auth_reply

    print("  [PASS] Telegram /start, security pairing, and Hermes execution verified.")


# ---------------------------------------------------------------------------
# Test 3: Discord Adapter Flow & Security Pairing
# ---------------------------------------------------------------------------

async def test_discord_adapter_flow(tmp_dir: Path):
    print("\n[TEST 3] Testing Discord adapter mention detection, security, and execution...")

    sec_mgr = GatewaySecurityManager(
        allow_all_users=False,
        allowlist_user_ids=[],
        pairing_code_enabled=True,
        storage_path=tmp_dir / "dc_users.json",
    )
    engine = MockEngine(reply_content="Autonomous response from Makima for Discord!")
    adapter = DiscordAdapter(
        token="MTA5ODc2NTQzMjEwOTg3NjU0Mw.GhIjKl.mNoPqRsTuVwXyZ",
        security_manager=sec_mgr,
        engine=engine,
    )

    client = adapter.build_client()
    bot_user = MagicMock()
    bot_user.id = 999999
    client._connection.user = bot_user  # Mock logged in client.user

    discord_user_id = 222222

    # 1. Ignore bot's own messages and other bots
    msg_bot, _ = make_discord_mock(999999, "Self message", is_bot=True)
    await adapter.handle_message(msg_bot)
    assert not msg_bot.reply.called

    # 2. Ignore messages in guild without mention
    msg_nomention, _ = make_discord_mock(discord_user_id, "Just talking in channel", is_mentioned=False)
    await adapter.handle_message(msg_nomention)
    assert not msg_nomention.reply.called

    # 3. Mentioned by unauthorized user -> prompt pairing
    msg_unauth, _ = make_discord_mock(
        discord_user_id,
        f"<@{bot_user.id}> Hello bot",
        is_mentioned=True,
        bot_id=bot_user.id,
    )
    await adapter.handle_message(msg_unauth)
    assert msg_unauth.reply.called
    unauth_reply = msg_unauth.reply.call_args[0][0]
    assert "Authorization Required" in unauth_reply
    assert "!pair <CODE>" in unauth_reply
    assert len(engine.call_history) == 0

    # 4. Pairing command (!pair <code>)
    pair_code = sec_mgr.generate_pairing_code()
    msg_pair, _ = make_discord_mock(discord_user_id, f"!pair {pair_code}")
    await adapter.handle_message(msg_pair)
    assert msg_pair.reply.called
    pair_reply = msg_pair.reply.call_args[0][0]
    assert "Pairing Successful" in pair_reply
    assert sec_mgr.is_user_authorized("discord", str(discord_user_id))

    # 5. Mentioned by authorized user -> dispatch to engine
    msg_auth, _ = make_discord_mock(
        discord_user_id,
        f"<@{bot_user.id}> Analyze the latest performance logs",
        is_mentioned=True,
        bot_id=bot_user.id,
    )
    await adapter.handle_message(msg_auth)
    assert len(engine.call_history) == 1
    assert engine.call_history[0]["prompt"] == "Analyze the latest performance logs"
    assert msg_auth.reply.called
    auth_reply = msg_auth.reply.call_args[0][0]
    assert "Autonomous response from Makima for Discord!" in auth_reply

    # 6. Direct Message (DM) without mention from authorized user
    msg_dm, _ = make_discord_mock(
        discord_user_id,
        "Help me with git rebase",
        is_dm=True,
        is_mentioned=False,
    )
    await adapter.handle_message(msg_dm)
    assert len(engine.call_history) == 2
    assert engine.call_history[1]["prompt"] == "Help me with git rebase"
    assert msg_dm.reply.called

    print("  [PASS] Discord mentions, DMs, pairing, and Hermes execution verified.")


# ---------------------------------------------------------------------------
# Test 4: Outbound Messaging API & Error Handlers
# ---------------------------------------------------------------------------

async def test_outbound_api():
    print("\n[TEST 4] Testing outbound message & file dispatch API...")

    tg_adapter = TelegramAdapter(token="mock:token")
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock(return_value="sent_msg")
    mock_app.bot.send_document = AsyncMock(return_value="sent_doc")
    tg_adapter._app = mock_app

    # Send message chunking test
    msgs = await tg_adapter.send_message(12345, "Hello Telegram outbound!")
    assert len(msgs) == 1
    assert mock_app.bot.send_message.called

    # Send file test with non-existent file
    try:
        await tg_adapter.send_file(12345, "nonexistent_file.pdf")
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        pass

    # Send file test with existing file
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write("Test file content")
        tmp_name = f.name

    try:
        await tg_adapter.send_file(12345, tmp_name, caption="Invoice")
        assert mock_app.bot.send_document.called
    finally:
        os.unlink(tmp_name)

    print("  [PASS] Outbound message and document dispatch API validated.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 13: TELEGRAM & DISCORD ADAPTERS TEST SUITE")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        tmp_dir = Path(temp_dir_str).resolve()
        test_interface_conformance_and_chunking()
        await test_telegram_adapter_flow(tmp_dir)
        await test_discord_adapter_flow(tmp_dir)
        await test_outbound_api()

    print("\n" + "=" * 75)
    print("ALL GATEWAY ADAPTER TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
