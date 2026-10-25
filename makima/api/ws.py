"""Makima v2 real-time WebSocket protocol with task correlation and cancel."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import ProviderResponse
from makima.runtime import build_engine, build_registry
from makima.tools.registry import ToolRegistry

logger = logging.getLogger("makima.api.ws")
router = APIRouter()


def _task_id(payload: Dict[str, Any]) -> str:
    value = payload.get("task_id") or payload.get("payload", {}).get("task_id")
    return str(value or f"task_{int(time.time() * 1000)}")


def _session_id(payload: Dict[str, Any], store: Any) -> str:
    value = payload.get("session_id") or payload.get("payload", {}).get("session_id")
    if value:
        session_id = str(value)[:160]
        if store.get_session(session_id):
            return session_id
        try:
            res = store.create_session(
                title=str(payload.get("title") or payload.get("content") or "New session")[:60],
                session_id=session_id,
            )
            if res and res.get("id"):
                return str(res["id"])
        except Exception:
            pass
        return session_id
    return str(store.create_session(str(payload.get("title") or "New session")).get("id"))


def _attachment_context(payload: Dict[str, Any]) -> str:
    """Turn bounded client-side attachment metadata into model context.

    The local UI deliberately sends text previews instead of writing arbitrary
    uploads to disk.  Keep this boundary strict so a client cannot inflate a
    prompt or smuggle path-like names into tool instructions.
    """
    raw_attachments = payload.get("attachments")
    if not isinstance(raw_attachments, list):
        return ""
    lines = []
    for item in raw_attachments[:5]:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "unnamed-file")[:180]
        name = re.sub(r"[^A-Za-z0-9._()\- ]", "_", raw_name).strip() or "unnamed-file"
        mime_type = str(item.get("mime_type") or "application/octet-stream")[:100]
        try:
            size = max(0, min(int(item.get("size") or 0), 8 * 1024 * 1024))
        except (TypeError, ValueError):
            size = 0
        preview = item.get("text_preview")
        if isinstance(preview, str) and preview:
            lines.append(f"[Attached file: {name}]\n{preview[:120_000]}")
        else:
            lines.append(f"[Attached file: {name} ({mime_type}, {size} bytes; no text preview available)]")
    return "\n\n".join(lines)


def _infer_tool_tags(content: str, prior_messages: Optional[List[Any]] = None) -> Optional[List[str]]:
    """
    Infers relevant tool tags from prompt keywords and recent turn tool usage
    to prevent tool schema attention dilution while preserving multi-turn context.
    Falls back to None (all tools) if no specific domain is confidently identified.
    """
    c = (content or "").lower().strip()
    if not c and not prior_messages:
        return None

    matched_tags: Set[str] = set()

    # Check prior messages for active domain continuity (e.g. prior turn used browser, search, or files)
    if prior_messages:
        for prev_msg in reversed(prior_messages[-4:]):
            if getattr(prev_msg, "tool_calls", None):
                for tc in prev_msg.tool_calls:
                    tc_name = getattr(tc, "name", "") or ""
                    if any(w in tc_name for w in ("browser", "web", "fetch", "search")):
                        matched_tags.update(["web", "browser", "fetch", "search"])
                    elif any(w in tc_name for w in ("file", "read", "write", "document")):
                        matched_tags.update(["filesystem", "documents", "io"])
                    elif any(w in tc_name for w in ("media", "spotify", "playback", "volume")):
                        matched_tags.update(["media", "music", "playback", "volume", "audio"])
                    elif any(w in tc_name for w in ("window", "screenshot", "mouse", "keyboard", "desktop")):
                        matched_tags.update(["desktop", "os", "apps", "windows"])

    # 1. Video/anime requests need browser tools, not music-only tools.
    # This scopes available tool schemas; the model still interprets the actual request.
    video_terms = (
        "anime", "episode", "episodes", "season", "seasons", "movie", "movies",
        "film", "films", "tv show", "series", "watch", "watching", "video", "videos",
        "trailer", "trailers", "amv", "miruro", "crunchyroll", "hidive", "aniwatch",
        "dekh", "dekhta", "dekhna", "dikhana",
    )
    is_video_request = any(term in c for term in video_terms)
    if is_video_request:
        # Remove media tags inherited from prior turns too, so play_song is not exposed
        # just because the preceding request was about music.
        matched_tags.difference_update({"media", "music", "playback", "volume", "audio"})
        matched_tags.update(["web", "browser", "fetch", "search"])
    else:
        # Music/audio and explicitly platform-specific playback requests.
        if any(k in c for k in (
            "play", "music", "song", "spotify", "youtube", "volume", "sound",
            "track", "pause", "resume", "audio", "gaana", "sunta", "playlist",
            "album", "artist", "singer", "listen",
        )):
            matched_tags.update(["media", "music", "playback", "volume", "audio", "browser", "web"])

    # 2. Web Browsing / Online Search
    if any(k in c for k in ("search", "google", "browse", "website", "url", "http", "click", "web", "fetch", "news", "price", "flipkart", "amazon", "miruro")):
        matched_tags.update(["web", "browser", "fetch", "search"])

    # 3. User Memory / Preferences / Habits
    if any(k in c for k in ("preference", "habit", "remember", "yaad", "profile", "pasand", "hamesha", "pe dekhta", "pe sunta", "dekhta hu", "sunta hu")):
        matched_tags.update(["memory", "facts", "preferences", "profile"])

    # 4. Desktop / OS / App Window Control
    if any(k in c for k in ("open app", "launch", "window", "screenshot", "desktop", "cursor", "click", "type", "keyboard", "mouse", "minimize", "maximize", "close app")):
        matched_tags.update(["desktop", "os", "apps", "windows", "input", "mouse", "keyboard", "computer_use"])

    # 5. Filesystem / Office Documents
    if any(k in c for k in ("file", "read", "write", "folder", "directory", "document", "excel", "sheet", "pdf", "word", "csv", "presentation", "powerpoint")):
        matched_tags.update(["filesystem", "documents", "excel", "word", "powerpoint", "reader", "io"])

    # 6. Messaging / Comms
    if any(k in c for k in ("whatsapp", "telegram", "discord", "email", "mail", "inbox", "send message", "contact")):
        matched_tags.update(["messaging", "whatsapp", "telegram", "discord", "email", "inbox"])

    # 7. Terminal / Code / Shell
    if any(k in c for k in ("terminal", "command", "bash", "powershell", "cmd", "run", "execute", "python", "script", "install", "pip")):
        matched_tags.update(["terminal", "execution", "sandbox", "filesystem", "system"])

    # 8. GitHub / Git / Repositories / Code Hosting
    if any(k in c for k in ("github", "git", "repo", "repositories", "commit", "pull request", "pr", "issue", "branch", "fork", "push", "clone", "gist")):
        matched_tags.update(["github", "git", "developer", "repositories", "code", "mcp", "terminal", "system"])

    # 9. MCP Plugins / Marketplace Extensions
    if any(k in c for k in ("mcp", "plugin", "extension", "marketplace", "sqlite", "database")):
        matched_tags.update(["plugin", "mcp", "openapi", "database", "sqlite"])

    if matched_tags:
        # Always inject fundamental core capabilities (memory facts + profile + web search) alongside domain tools
        matched_tags.update(["memory", "facts", "preferences", "web", "search"])
        return sorted(matched_tags)

    # Safe bounded fallback for general conversation — prevents exceeding free model token limits (e.g. Groq 8000 TPM)
    return sorted(["memory", "facts", "preferences", "web", "search", "media"])


@router.websocket("/ws")
async def websocket_bridge(websocket: WebSocket) -> None:
    """Serve the Makima event stream without blocking the receive loop."""
    origin = websocket.headers.get("origin", "").rstrip("/")
    allowed_origins = set(getattr(websocket.app.state, "allowed_ui_origins", []))
    if origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="Origin is not allowed for this local Makima instance.")
        return
    await websocket.accept()
    engine: Optional[HermesAgentEngine] = getattr(websocket.app.state, "engine", None)
    registry: ToolRegistry = getattr(websocket.app.state, "registry", None) or build_registry()
    session_store = getattr(websocket.app.state, "session_store", None)
    running: Dict[str, asyncio.Task[Any]] = {}
    send_lock = asyncio.Lock()
    connection_session_id: Optional[str] = None

    async def send(event: Dict[str, Any], task_id: Optional[str] = None) -> None:
        if task_id and "task_id" not in event:
            event["task_id"] = task_id
        try:
            async with send_lock:
                await websocket.send_json(event)
        except Exception as exc:
            logger.debug("WebSocket send failed: %s", exc)

    async def run_message(payload: Dict[str, Any], current_task_id: str) -> None:
        nonlocal engine, connection_session_id
        req_session_id = payload.get("session_id") or payload.get("payload", {}).get("session_id")
        if req_session_id:
            current_session_id = str(req_session_id)[:160]
            connection_session_id = current_session_id
        elif connection_session_id:
            current_session_id = connection_session_id
        elif session_store:
            current_session_id = _session_id(payload, session_store)
            connection_session_id = current_session_id
        else:
            current_session_id = ""

        user_message_id = str(payload.get("message_id") or f"message_{current_task_id}")[:160]
        if engine is None:
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                engine = build_engine(registry=registry)
                websocket.app.state.engine = engine

        content = payload.get("content")
        if content is None:
            content = payload.get("payload", {}).get("text", "")
        content = str(content).strip()
        attachment_context = _attachment_context(payload)
        if attachment_context:
            content = f"{content}\n\nAttached files:\n{attachment_context}".strip()
        if not content:
            await send({"type": "error", "message": "Field 'content' cannot be empty in 'user_message'."}, current_task_id)
            return

        if session_store:
            session_store.add_message(current_session_id, user_message_id, "user", content, metadata={"operation": payload.get("operation", "send")})

        session_messages = None
        _POISON_PREFIXES = (
            "Makima could not complete this task.",
            "Task cancelled.",
            "[MAX_TURNS_EXCEEDED]",
        )

        # 1. Primary: Rehydrate rich history (with tool calls and tool results) from EpisodicMemory
        if engine and engine.episodic_memory is not None and current_session_id:
            try:
                episodic_msgs = await engine.episodic_memory.get_recent_messages(current_session_id, limit=100)
                if episodic_msgs:
                    filtered_msgs = []
                    for m in episodic_msgs:
                        if m.role == "assistant" and any(str(m.content or "").startswith(p) for p in _POISON_PREFIXES):
                            if filtered_msgs and filtered_msgs[-1].role == "user":
                                filtered_msgs.pop()
                            continue
                        filtered_msgs.append(m)
                    if filtered_msgs and filtered_msgs[-1].role == "user" and filtered_msgs[-1].content == content:
                        filtered_msgs.pop()
                    session_messages = filtered_msgs
            except Exception as e:
                logger.debug("Episodic history load in ws.py skipped: %s", e)

        # 2. Fallback: If EpisodicMemory had no entries or failed, rehydrate from SessionStore
        if session_messages is None and session_store:
            stored = session_store.get_session(current_session_id)
            if stored:
                from makima.provider.adapters.base import Message
                filtered_msgs = []
                for item in stored.get("messages", []):
                    role = item.get("role", "user")
                    if role not in {"user", "assistant"}:
                        continue
                    msg_content = str(item.get("content") or "").strip()
                    if not msg_content:
                        continue
                    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    if role == "assistant" and (
                        meta.get("error")
                        or meta.get("cancelled")
                        or any(msg_content.startswith(p) for p in _POISON_PREFIXES)
                    ):
                        if filtered_msgs and filtered_msgs[-1].role == "user":
                            filtered_msgs.pop()
                        continue
                    filtered_msgs.append(Message(role=role, content=msg_content))
                    if role == "assistant":
                        tool_trace = meta.get("tool_trace")
                        if isinstance(tool_trace, list) and tool_trace:
                            trace_str = "; ".join(str(t) for t in tool_trace[:8] if t)
                            if trace_str:
                                filtered_msgs.append(Message(role="system", content=f"[System Telemetry: Prior turn executed {trace_str}]"))
                session_messages = filtered_msgs
                if session_messages and session_messages[-1].role == "user" and session_messages[-1].content == content:
                    session_messages.pop()

        await send({"type": "status", "stage": "planning", "session_id": current_session_id, "message_id": user_message_id}, current_task_id)

        executed_tool_trace: list[str] = []
        executed_steps: list[Dict[str, Any]] = []

        def _safe_serialize(val: Any) -> Any:
            if val is None or isinstance(val, (int, float, bool, str)):
                return val
            if isinstance(val, (list, tuple)):
                return [_safe_serialize(x) for x in val[:50]]
            if isinstance(val, dict):
                return {str(k): _safe_serialize(v) for k, v in list(val.items())[:50]}
            return str(val)

        def _format_tool_trace_entry(name: str, args: Dict[str, Any], res: Any) -> str:
            key_parts = []
            for k in ("action", "url", "query", "selector", "index", "text", "app_name", "path"):
                if k in args and args[k] is not None and str(args[k]).strip():
                    val = str(args[k]).strip().replace("\n", " ")[:100]
                    key_parts.append(f"{k}='{val}'")
            arg_summary = ", ".join(key_parts)
            status = "ok"
            if isinstance(res, dict):
                if res.get("success") is False or res.get("error"):
                    status = f"error({str(res.get('error') or 'failed')[:60]})"
                elif res.get("url") or res.get("current_url"):
                    u = str(res.get("url") or res.get("current_url"))[:100]
                    status = f"ok(url={u})"
            elif isinstance(res, str) and (res.startswith("[TOOL_FAILED") or res.startswith("[TOOL_DISABLED")):
                status = res[:80]
            return f"{name}({arg_summary}) -> {status}"

        async def ws_tool_executor(name: str, args: Dict[str, Any]) -> Any:
            call_id = f"call_{int(time.time() * 1000)}"
            start_ts = time.time()
            stage_display = f"Executing {name}..."
            if name == "browser_interact":
                action_name = str((args or {}).get("action") or "").lower()
                stage_display = f"Browsing live web ({action_name})..." if action_name else "Browsing live web..."
            elif name in ("web_search", "search_web"):
                q_text = str((args or {}).get("query") or "")[:30]
                stage_display = f"Searching web: '{q_text}'..." if q_text else "Searching web..."
            elif name in ("fetch_page", "fetch_web_page"):
                stage_display = "Fetching webpage content..."
            elif name in ("execute_command", "run_command"):
                c_text = str((args or {}).get("command") or "")[:30]
                stage_display = f"Running command: '{c_text}'..." if c_text else "Executing command..."

            step_entry: Dict[str, Any] = {
                "id": call_id,
                "type": "tool",
                "name": name,
                "stage": stage_display,
                "arguments": _safe_serialize(args or {}),
                "status": "running",
                "timestamp": int(start_ts * 1000),
            }
            executed_steps.append(step_entry)

            await send({"type": "tool_call", "id": call_id, "name": name, "arguments": args}, current_task_id)
            await send({"type": "status", "stage": stage_display, "tool": name}, current_task_id)
            if name in getattr(websocket.app.state, "disabled_tools", set()):
                result: Any = f"[TOOL_DISABLED: {name}] Tool disabled in Makima settings."
            else:
                try:
                    result = await registry.execute(name, args)
                except Exception as err:
                    result = f"[TOOL_FAILED: {name}] {type(err).__name__}: {str(err)}"
            try:
                executed_tool_trace.append(_format_tool_trace_entry(name, args or {}, result))
            except Exception:
                pass

            duration_ms = int((time.time() - start_ts) * 1000)
            is_err = False
            err_text: Optional[str] = None
            if isinstance(result, str) and (result.startswith("[TOOL_FAILED") or result.startswith("[TOOL_DISABLED")):
                is_err = True
                err_text = result[:120]
            elif isinstance(result, dict) and (result.get("success") is False or result.get("error")):
                is_err = True
                err_text = str(result.get("error") or "failed")[:120]

            step_entry["status"] = "failed" if is_err else "completed"
            step_entry["result"] = _safe_serialize(result)
            step_entry["durationMs"] = duration_ms
            if is_err:
                step_entry["error"] = err_text

            await send({"type": "tool_result", "id": call_id, "name": name, "result": result, "duration_ms": duration_ms}, current_task_id)
            if is_err:
                await send({
                    "type": "status",
                    "stage": f"⚠️ {name} failed — trying alternate approach...",
                    "tool": name,
                    "error": err_text,
                }, current_task_id)
            return result

        async def on_turn_end(turn: int, response: ProviderResponse) -> None:
            if response.tool_calls and response.content and response.content.strip():
                content_text = response.content.strip()
                executed_steps.append({
                    "id": f"thought_{turn}_{int(time.time() * 1000)}",
                    "type": "thought",
                    "stage": content_text,
                    "status": "completed",
                    "timestamp": int(time.time() * 1000),
                })
                # Stream intermediate assistant thought / explanation so user sees it in real-time
                await send({
                    "type": "thought",
                    "content": content_text,
                    "turn": turn,
                    "session_id": current_session_id,
                }, current_task_id)
            stage = "dispatching_tools" if response.tool_calls else "generating_response"
            await send({"type": "status", "stage": stage, "turn": turn}, current_task_id)

        try:
            ui_cfg = getattr(websocket.app.state, "ui_settings", {}) or {}
            thinking_mode = payload.get("thinking_mode") or ui_cfg.get("thinking_mode")
            resolved_temp = payload.get("temperature")
            if resolved_temp is None:
                try:
                    resolved_temp = float(ui_cfg.get("temperature", 0.2))
                except (ValueError, TypeError):
                    resolved_temp = 0.2
            inferred_tags = _infer_tool_tags(content, prior_messages=session_messages)
            if inferred_tags is not None and registry is not None:
                if len(registry.list_tools(tags=inferred_tags)) < 5:
                    inferred_tags = None
            result = await engine.run(
                prompt=content,
                messages=session_messages,
                system_prompt=payload.get("system_prompt"),
                tools=registry,
                tool_executor=ws_tool_executor,
                task=payload.get("task", "fast_chat"),
                temperature=resolved_temp,
                max_turns=payload.get("max_turns"),
                preferred_backend=payload.get("backend") or payload.get("provider"),
                on_turn_end=on_turn_end,
                session_id=current_session_id or None,
                tool_tags=inferred_tags,
                thinking_mode=thinking_mode,
            )
            await send({
                "type": "message", "content": result.content, "model": result.model_used,
                "turn_count": result.turn_count, "completed": result.completed,
                "finish_reason": result.finish_reason, "latency_ms": result.latency_ms,
                "artifacts": getattr(result, "artifacts", None) or [],
                "suggestions": getattr(result, "suggestions", None) or [],
                "steps": executed_steps,
                "session_id": current_session_id,
                "message_id": f"assistant_{current_task_id}",
                "parent_message_id": user_message_id,
                "variant_id": str(payload.get("variant_id") or "default"),
            }, current_task_id)
            if session_store:
                session_store.add_message(
                    current_session_id,
                    f"assistant_{current_task_id}",
                    "assistant",
                    result.content,
                    parent_message_id=user_message_id,
                    variant_id=str(payload.get("variant_id") or "default"),
                    metadata={
                        "model": result.model_used,
                        "finish_reason": result.finish_reason,
                        "suggestions": getattr(result, "suggestions", None) or [],
                        "tool_trace": executed_tool_trace[:12],
                        "steps": executed_steps,
                    },
                )
            await send({"type": "status", "stage": "completed", "latency_ms": result.latency_ms}, current_task_id)
        except asyncio.CancelledError:
            if executed_steps and executed_steps[-1].get("status") == "running":
                executed_steps[-1]["status"] = "failed"
                executed_steps[-1]["error"] = "Cancelled by client"
            try:
                if session_store:
                    session_store.add_message(
                        current_session_id,
                        f"assistant_{current_task_id}",
                        "assistant",
                        "Task cancelled.",
                        parent_message_id=user_message_id,
                        metadata={"cancelled": True, "steps": executed_steps},
                    )
                await send({"type": "task_cancelled", "reason": "cancelled_by_client", "steps": executed_steps}, current_task_id)
                await send({"type": "status", "stage": "cancelled"}, current_task_id)
            except Exception as e:
                logger.debug("Exception during cancel cleanup: %s", e)
            raise
        except Exception as run_exc:
            logger.error("Error during agent execution: %s", run_exc, exc_info=True)
            if executed_steps and executed_steps[-1].get("status") == "running":
                executed_steps[-1]["status"] = "failed"
                executed_steps[-1]["error"] = str(run_exc)[:200]
            if session_store:
                session_store.add_message(
                    current_session_id,
                    f"assistant_{current_task_id}",
                    "assistant",
                    "Makima could not complete this task.",
                    parent_message_id=user_message_id,
                    metadata={"error": type(run_exc).__name__, "steps": executed_steps},
                )
            await send({"type": "error", "message": str(run_exc), "steps": executed_steps, "session_id": current_session_id, "message_id": f"assistant_{current_task_id}"}, current_task_id)
            await send({"type": "status", "stage": "error"}, current_task_id)
        finally:
            running.pop(current_task_id, None)
            active_set = getattr(websocket.app.state, "active_tasks", None)
            if active_set is not None:
                current_t = asyncio.current_task()
                if current_t:
                    active_set.discard(current_t)

    try:
        while True:
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.warning("Error receiving WebSocket frame: %s", exc)
                break

            try:
                payload = json.loads(raw_data)
            except Exception:
                await send({"type": "error", "message": "Malformed JSON payload received."})
                continue

            if not isinstance(payload, dict):
                await send({"type": "error", "message": "Expected JSON object dictionary payload."})
                continue

            msg_type = payload.get("type")
            if msg_type == "ping":
                await send({"type": "pong", "timestamp": time.time()})
            elif msg_type == "cancel_task":
                cancel_id = str(payload.get("task_id") or payload.get("payload", {}).get("task_id") or "")
                task = running.get(cancel_id)
                if not task and len(running) == 1:
                    cancel_id, task = next(iter(running.items()))
                if task and not task.done():
                    task.cancel()
                else:
                    await send({"type": "task_cancelled", "reason": "task_not_running"}, cancel_id or None)
            elif msg_type == "user_message":
                current_task_id = _task_id(payload)
                previous = running.get(current_task_id)
                if previous and not previous.done():
                    await send({"type": "error", "message": "task_id is already running"}, current_task_id)
                    continue
                new_task = asyncio.create_task(run_message(payload, current_task_id))
                running[current_task_id] = new_task
                active_set = getattr(websocket.app.state, "active_tasks", None)
                if active_set is not None:
                    active_set.add(new_task)
            else:
                await send({"type": "error", "message": f"Unsupported message type '{msg_type}'. Expected 'user_message', 'cancel_task', or 'ping'."})
    finally:
        # Note: In-flight agent tasks are decoupled from transient browser disconnects (e.g. back button / refresh).
        # They continue running in the background and persist their completed message to SessionStore.
        # Explicit cancel is handled via 'cancel_task' or lifespan shutdown.
        logger.info("WebSocket disconnected (%d task(s) continuing in background).", len(running))
