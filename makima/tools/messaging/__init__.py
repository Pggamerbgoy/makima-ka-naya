"""
Makima v2 — Messaging & Universal Inbox Tools.
Architectural Pattern: Dynamic Hermes @tool implementations for multi-platform communication.
"""

from makima.tools.messaging.inbox import (
    configure_vip_contacts,
    get_inbox_messages,
    mark_inbox_messages_read,
    summarize_inbox,
)
from makima.tools.messaging.whatsapp import (
    check_whatsapp_status,
    send_whatsapp_message,
)

__all__ = [
    "summarize_inbox",
    "get_inbox_messages",
    "configure_vip_contacts",
    "mark_inbox_messages_read",
    "send_whatsapp_message",
    "check_whatsapp_status",
]
