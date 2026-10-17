"""
Makima v2 — Multi-platform messaging gateway daemon for Telegram, Discord, WhatsApp, and Email.
"""

from __future__ import annotations

from makima.gateway.adapters import (
    BaseAdapter,
    DiscordAdapter,
    EmailAdapter,
    TelegramAdapter,
    WhatsAppAdapter,
    normalize_whatsapp_jid,
    parse_email_message,
    split_message,
)
from makima.gateway.daemon import GatewayDaemon
from makima.gateway.inbox import (
    InboxManager,
    InboxMessage,
    InboxStore,
    PriorityClassifier,
    PriorityLevel,
    get_inbox_manager,
    reset_inbox_manager,
)
from makima.gateway.scheduler import GatewayScheduler
from makima.gateway.security import GatewaySecurityManager

__all__ = [
    "GatewayDaemon",
    "GatewayScheduler",
    "GatewaySecurityManager",
    "BaseAdapter",
    "TelegramAdapter",
    "DiscordAdapter",
    "EmailAdapter",
    "WhatsAppAdapter",
    "split_message",
    "parse_email_message",
    "normalize_whatsapp_jid",
    "InboxMessage",
    "PriorityLevel",
    "PriorityClassifier",
    "InboxStore",
    "InboxManager",
    "get_inbox_manager",
    "reset_inbox_manager",
]
