"""
Makima v2 — FastAPI Application & Real-time WebSocket Bridge.
Exports application factory and endpoints.
"""

from makima.api.app import create_app

__all__ = [
    "create_app",
]
