"""
Makima v2 — WhatsApp Messaging & Integration Tools.
Provides dynamic WhatsApp sending, bridge health inspection, and desktop protocol fallbacks.
Supports both headless Baileys HTTP bridge daemons and native desktop URI protocol integration.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any, Dict, Optional

import httpx

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _normalize_phone_number(recipient: str) -> str:
    """Standardizes phone number by removing non-digits and suffixes."""
    s = str(recipient).strip()
    if "@" in s:
        s = s.split("@")[0]
    digits = re.sub(r"\D", "", s)
    return digits or s


@tool(
    name="send_whatsapp_message",
    description="Send a WhatsApp message to a phone number or contact. Uses the local WhatsApp bridge if active, or generates a native desktop launch URI.",
    tags=["messaging", "whatsapp", "communication"],
    purpose="Send automated or requested WhatsApp text messages to a recipient.",
    side_effect="Transmits a message via WhatsApp bridge or launches WhatsApp Desktop.",
)
def send_whatsapp_message(
    recipient: str,
    message: str,
    bridge_url: Optional[str] = None,
    open_desktop_if_offline: bool = False,
) -> Dict[str, Any]:
    """
    Send a WhatsApp text message.

    Args:
        recipient: Target phone number with country code (e.g. '919876543210' or '+91 98765 43210').
        message: The text content to transmit.
        bridge_url: Optional custom HTTP bridge URL. Defaults to WHATSAPP_BRIDGE_URL env var or http://localhost:3001.
        open_desktop_if_offline: If True and the bridge daemon is offline, attempts to open WhatsApp Desktop with pre-filled text.

    Returns:
        Dictionary reporting delivery status, recipient, and details.
    """
    phone = _normalize_phone_number(recipient)
    if not phone or len(phone) < 5:
        return {
            "success": False,
            "error": f"Invalid recipient phone number '{recipient}'. Please include country code without spaces (e.g. 919876543210).",
        }

    clean_message = (message or "").strip()
    if not clean_message:
        return {
            "success": False,
            "error": "Message content cannot be empty.",
        }

    target_bridge = bridge_url or os.getenv("WHATSAPP_BRIDGE_URL", "")
    api_key = os.getenv("WHATSAPP_API_KEY", "")

    # Strategy 1: Post to local/remote Baileys WhatsApp HTTP Bridge
    if target_bridge:
        endpoint = f"{target_bridge.rstrip('/')}/send-message"
        headers: Dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-Api-Key"] = api_key

        payload = {
            "to": f"{phone}@s.whatsapp.net",
            "message": clean_message,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    return {
                        "success": True,
                        "status": "delivered_via_bridge",
                        "recipient": phone,
                        "bridge_url": target_bridge,
                        "message_preview": clean_message[:80],
                    }
                else:
                    logger.warning("WhatsApp bridge returned status %s: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.debug("Failed connecting to WhatsApp bridge at %s: %s", endpoint, exc)

    # Strategy 2: Native WhatsApp Desktop / Web URI Protocol
    encoded_text = urllib.parse.quote(clean_message)
    native_uri = f"whatsapp://send?phone={phone}&text={encoded_text}"
    web_uri = f"https://wa.me/{phone}?text={encoded_text}"

    desktop_opened = False
    if open_desktop_if_offline:
        try:
            from makima.tools.os.app_opener import launch_application
            # Try launching the URI via system default handler
            launch_application(target=native_uri)
            desktop_opened = True
        except Exception as exc:
            logger.debug("Could not launch WhatsApp protocol URI: %s", exc)

    return {
        "success": True,
        "status": "desktop_ready" if desktop_opened else "bridge_offline_ready",
        "recipient": phone,
        "desktop_opened": desktop_opened,
        "native_uri": native_uri,
        "web_link": web_uri,
        "message": (
            f"WhatsApp bridge is not active. Pre-filled message prepared for +{phone} via WhatsApp Desktop."
            if not desktop_opened
            else f"Launched WhatsApp Desktop with pre-filled message for +{phone}."
        ),
    }


@tool(
    name="check_whatsapp_status",
    description="Check the connectivity status of the local WhatsApp bridge (Baileys/whatsapp-web daemon) and authentication state.",
    tags=["messaging", "whatsapp", "diagnostics"],
    purpose="Inspect whether WhatsApp integration is live, authenticated, or needs pairing.",
    side_effect="Read-only HTTP query.",
)
def check_whatsapp_status(
    bridge_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Check the connectivity status of the WhatsApp bridge daemon.

    Args:
        bridge_url: Optional URL of the bridge server. Defaults to WHATSAPP_BRIDGE_URL or http://localhost:3001.

    Returns:
        Dictionary reporting connection state, authentication status, and instructions.
    """
    target_bridge = bridge_url or os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:3001")
    endpoint = f"{target_bridge.rstrip('/')}/status"
    api_key = os.getenv("WHATSAPP_API_KEY", "")

    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(endpoint, headers=headers)
            if resp.status_code == 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                return {
                    "connected": True,
                    "bridge_online": True,
                    "bridge_url": target_bridge,
                    "authenticated": data.get("authenticated", True),
                    "phone": data.get("phone", "connected"),
                    "details": data,
                }
    except Exception as exc:
        logger.debug("WhatsApp bridge status check failed: %s", exc)

    return {
        "connected": False,
        "bridge_online": False,
        "bridge_url": target_bridge,
        "authenticated": False,
        "instructions": (
            "WhatsApp bridge daemon is not running on localhost:3001. "
            "To enable 100% background WhatsApp access without browser popups, start the local Baileys bridge or run 'makima gateway start'."
        ),
    }
