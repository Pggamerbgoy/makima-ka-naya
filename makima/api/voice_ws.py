"""Browser-to-Gemini Live audio bridge.

The browser sends raw microphone PCM frames to this endpoint.  Gemini's API key
and the Makima tool registry stay on the server; only audio/status frames cross
the browser WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from makima.voice.gemini_live import DEFAULT_LIVE_MODEL, GeminiLiveSession

logger = logging.getLogger("makima.api.voice_ws")
router = APIRouter()


@router.websocket("/ws/voice")
async def voice_bridge(websocket: WebSocket) -> None:
    """Proxy a browser voice session to Gemini Live without exposing credentials."""
    origin = websocket.headers.get("origin", "").rstrip("/")
    allowed_origins = set(getattr(websocket.app.state, "allowed_ui_origins", []))
    if origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="Origin is not allowed for this local Makima instance.")
        return
    await websocket.accept()
    session: Optional[GeminiLiveSession] = None
    receive_task: Optional[asyncio.Task[Any]] = None
    session_id = f"voice_{uuid.uuid4().hex[:12]}"
    send_lock = asyncio.Lock()

    async def send_json(event: Dict[str, Any]) -> None:
        event.setdefault("session_id", session_id)
        async with send_lock:
            await websocket.send_json(event)

    async def forward_events(active_session: GeminiLiveSession) -> None:
        try:
            async for event in active_session.receive_events():
                event_type = event.get("type")
                if event_type == "audio":
                    data = event.get("data")
                    if data:
                        async with send_lock:
                            await websocket.send_bytes(data)
                else:
                    await send_json({k: v for k, v in event.items() if k != "data"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Gemini Live receive loop failed: %s", exc)
            await send_json({"type": "voice_error", "message": str(exc)})

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            binary = message.get("bytes")
            if binary is not None:
                if session and session.is_active:
                    await session.send_audio_chunk(binary)
                continue

            raw = message.get("text")
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await send_json({"type": "voice_error", "message": "Malformed voice control message."})
                continue

            event_type = payload.get("type")
            if event_type == "start":
                if session and session.is_active:
                    await send_json({"type": "voice_ready", "model": session.model, "already_active": True})
                    continue
                session = GeminiLiveSession(
                    model=str(payload.get("model") or DEFAULT_LIVE_MODEL),
                    voice_name=str(payload.get("voice_name") or "Aoede"),
                )
                try:
                    await session.connect()
                    receive_task = asyncio.create_task(forward_events(session))
                    await send_json({"type": "voice_ready", "model": session.model, "voice_name": session.voice_name})
                except Exception as exc:
                    await send_json({"type": "voice_error", "message": str(exc)})
                    await session.close()
                    session = None
            elif event_type == "stop":
                if receive_task:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
                    receive_task = None
                if session:
                    await session.close()
                    session = None
                await send_json({"type": "voice_stopped"})
            elif event_type == "ping":
                await send_json({"type": "voice_pong"})
            else:
                await send_json({"type": "voice_error", "message": f"Unsupported voice event '{event_type}'."})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("Voice WebSocket failed: %s", exc)
    finally:
        if receive_task:
            receive_task.cancel()
            await asyncio.gather(receive_task, return_exceptions=True)
        if session:
            await session.close()
