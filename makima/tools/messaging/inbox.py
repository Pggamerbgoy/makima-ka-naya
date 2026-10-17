"""
Makima v2 — Universal Inbox Summarizer & VIP Manager Tools.
Architectural Pattern: Dynamic Hermes @tool integration with InboxManager & SQLite store.
Features:
- On-Demand Cross-Platform Summarization (WhatsApp, Telegram, Discord, Email).
- Zero background LLM consumption — only evaluates when user explicitly prompts.
- Dynamic VIP sender configuration for boss, family, clients.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from makima.gateway.inbox import PriorityLevel, get_inbox_manager
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="summarize_inbox",
    description="Summarize unread or recent messages across messaging platforms (WhatsApp, Email, Telegram, Discord, or all) with priority categorizations.",
    tags=["messaging", "inbox", "summary", "whatsapp", "email", "telegram", "discord"],
)
def summarize_inbox(
    platform: str = "all",
    unread_only: bool = True,
    hours: int = 24,
) -> Dict[str, Any]:
    """
    Summarizes messages across platforms for the user.

    Args:
        platform: Platform to filter ('all', 'whatsapp', 'email', 'telegram', 'discord'). Default 'all'.
        unread_only: If True (default), summarizes only unread messages.
        hours: How many hours back to inspect (default: 24).

    Returns:
        Structured dictionary with categorized message counts, breakdown, and formatted summary briefing.
    """
    inbox_mgr = get_inbox_manager()
    messages = inbox_mgr.store.get_messages(
        platform=platform,
        unread_only=unread_only,
        limit=100,
        hours=float(hours),
    )

    if not messages:
        status_msg = f"No {'unread ' if unread_only else ''}messages found for '{platform}' in the last {hours} hours."
        return {
            "success": True,
            "total_count": 0,
            "platform": platform,
            "unread_only": unread_only,
            "summary": status_msg,
            "critical_count": 0,
            "high_count": 0,
            "normal_count": 0,
            "low_count": 0,
            "messages": [],
        }

    # Group messages by priority
    critical_msgs = [m for m in messages if m.importance_level == PriorityLevel.CRITICAL.value]
    high_msgs = [m for m in messages if m.importance_level == PriorityLevel.HIGH.value]
    normal_msgs = [m for m in messages if m.importance_level == PriorityLevel.NORMAL.value]
    low_msgs = [m for m in messages if m.importance_level == PriorityLevel.LOW.value]

    # Format human-friendly executive briefing
    lines: List[str] = [
        f"### 📬 Inbox Briefing: {platform.upper()} ({len(messages)} {'unread ' if unread_only else ''}messages in last {hours}h)",
        "",
    ]

    if critical_msgs:
        lines.append("#### 🚨 Critical / Urgent Action Items:")
        for m in critical_msgs:
            dt_str = datetime.datetime.fromtimestamp(m.timestamp).strftime("%H:%M")
            sender = m.sender_name or m.sender_id
            subj = f" - *{m.subject}*" if m.subject else ""
            lines.append(f"- **[{m.platform.upper()}] {sender}** ({dt_str}){subj}: {m.content[:150]}")
            if m.importance_reason:
                lines.append(f"  *(Reason: {m.importance_reason})*")
        lines.append("")

    if high_msgs:
        lines.append("#### ⚡ Important / Priority Updates:")
        for m in high_msgs:
            dt_str = datetime.datetime.fromtimestamp(m.timestamp).strftime("%H:%M")
            sender = m.sender_name or m.sender_id
            subj = f" - *{m.subject}*" if m.subject else ""
            lines.append(f"- **[{m.platform.upper()}] {sender}** ({dt_str}){subj}: {m.content[:140]}")
            if m.importance_reason:
                lines.append(f"  *(Reason: {m.importance_reason})*")
        lines.append("")

    if normal_msgs:
        lines.append("#### 💬 Regular Messages:")
        for m in normal_msgs[:10]:
            dt_str = datetime.datetime.fromtimestamp(m.timestamp).strftime("%H:%M")
            sender = m.sender_name or m.sender_id
            subj = f" - *{m.subject}*" if m.subject else ""
            lines.append(f"- **[{m.platform.upper()}] {sender}** ({dt_str}){subj}: {m.content[:100]}")
        if len(normal_msgs) > 10:
            lines.append(f"- *...and {len(normal_msgs) - 10} more regular messages.*")
        lines.append("")

    if low_msgs:
        lines.append(f"#### 🏷️ Promotional / Newsletters / Low Priority ({len(low_msgs)} messages omitted from active briefing)")

    summary_text = "\n".join(lines).strip()

    return {
        "success": True,
        "total_count": len(messages),
        "platform": platform,
        "unread_only": unread_only,
        "critical_count": len(critical_msgs),
        "high_count": len(high_msgs),
        "normal_count": len(normal_msgs),
        "low_count": len(low_msgs),
        "summary": summary_text,
        "messages": [m.to_dict() for m in messages[:30]],
    }


@tool(
    name="get_inbox_messages",
    description="Retrieve a raw list of messages from the Makima inbox store with optional platform, unread, or importance level filtering.",
    tags=["messaging", "inbox", "query"],
)
def get_inbox_messages(
    platform: str = "all",
    unread_only: bool = True,
    limit: int = 20,
    min_importance: str = "normal",
) -> Dict[str, Any]:
    """
    Fetch raw list of messages stored in the universal inbox.

    Args:
        platform: Filter by platform ('all', 'whatsapp', 'email', 'telegram', 'discord'). Default 'all'.
        unread_only: If True (default), only retrieves unread messages.
        limit: Max number of messages to return (default 20).
        min_importance: Minimum priority level ('low', 'normal', 'high', 'critical'). Default 'normal'.

    Returns:
        Dictionary with count and list of serialized message records.
    """
    inbox_mgr = get_inbox_manager()
    messages = inbox_mgr.store.get_messages(
        platform=platform,
        unread_only=unread_only,
        limit=limit,
        min_importance=min_importance if min_importance != "all" else None,
    )

    return {
        "success": True,
        "count": len(messages),
        "platform": platform,
        "messages": [m.to_dict() for m in messages],
    }


@tool(
    name="configure_vip_contacts",
    description="Manage VIP contacts (add, remove, or list) whose incoming messages are automatically given HIGH priority.",
    tags=["messaging", "vip", "contacts", "settings"],
)
def configure_vip_contacts(
    action: str = "list",
    contact: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Configure or inspect VIP contacts.

    Args:
        action: 'add', 'remove', or 'list'.
        contact: Phone number, email address, or name (required for 'add' and 'remove').
        notes: Optional note (e.g. 'Boss', 'Mom', 'Key Client').

    Returns:
        Status result and current list of VIP contacts.
    """
    inbox_mgr = get_inbox_manager()
    clean_action = action.lower().strip()

    if clean_action == "add":
        if not contact or not contact.strip():
            return {"success": False, "error": "A 'contact' string must be provided to add a VIP."}
        clean_contact = contact.strip()
        inbox_mgr.add_vip(clean_contact, notes)
        return {
            "success": True,
            "action": "added",
            "contact": clean_contact,
            "vips": inbox_mgr.list_vips(),
        }

    elif clean_action == "remove":
        if not contact or not contact.strip():
            return {"success": False, "error": "A 'contact' string must be provided to remove a VIP."}
        clean_contact = contact.strip()
        removed = inbox_mgr.remove_vip(clean_contact)
        return {
            "success": True,
            "action": "removed",
            "contact": clean_contact,
            "was_removed": removed,
            "vips": inbox_mgr.list_vips(),
        }

    elif clean_action == "list":
        return {
            "success": True,
            "action": "list",
            "vips": inbox_mgr.list_vips(),
        }

    return {
        "success": False,
        "error": f"Unknown action '{action}'. Supported actions are 'add', 'remove', and 'list'.",
    }


@tool(
    name="mark_inbox_messages_read",
    description="Mark inbox messages as read by specific message IDs or by platform.",
    tags=["messaging", "inbox", "read"],
)
def mark_inbox_messages_read(
    message_ids: Optional[List[str]] = None,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mark messages as read in the inbox store.

    Args:
        message_ids: Optional list of message ID strings to mark read.
        platform: Optional platform ('whatsapp', 'email', 'telegram', 'discord', 'all') to mark all unread messages as read.

    Returns:
        Dictionary indicating number of messages updated.
    """
    inbox_mgr = get_inbox_manager()
    count = inbox_mgr.store.mark_as_read(message_ids=message_ids, platform=platform)
    return {
        "success": True,
        "marked_read_count": count,
        "remaining_unread": inbox_mgr.store.get_unread_count(platform=platform or "all"),
    }
