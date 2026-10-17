"""
Makima v2 — Gateway Adapters Package.
Multi-platform messaging integrations for Telegram, Discord, Email, and WhatsApp with pairing security.
"""

from __future__ import annotations

from makima.gateway.adapters.base import BaseAdapter, split_message
from makima.gateway.adapters.discord import DiscordAdapter
from makima.gateway.adapters.email_daemon import EmailAdapter, parse_email_message
from makima.gateway.adapters.telegram import TelegramAdapter
from makima.gateway.adapters.whatsapp import WhatsAppAdapter, normalize_whatsapp_jid

__all__ = [
    "BaseAdapter",
    "TelegramAdapter",
    "DiscordAdapter",
    "EmailAdapter",
    "WhatsAppAdapter",
    "split_message",
    "parse_email_message",
    "normalize_whatsapp_jid",
]
