"""
Makima v2 — FastAPI Application & REST Endpoints.
Architectural Pattern: Modern FastAPI async server with CORS, telemetry, dynamic ToolRegistry introspection,
and autonomous HermesAgentEngine dispatch.
Zero-Hardcoding Guarantee: Fully dynamic provider status and schema discovery.
"""

from __future__ import annotations

import asyncio
import logging
import json
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import makima
from makima.core.http_pool import close_shared_client, get_shared_client
from makima.api.ws import router as ws_router
from makima.api.voice_ws import router as voice_ws_router
from makima.api.sessions import SessionStore
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import Message
from makima.provider.cache import get_cache_manager
from makima.provider.router import ParetoRouter
from makima.runtime import build_engine, build_plugin_manager, build_registry, load_session_messages
from makima.tools.registry import ToolRegistry, get_registry
from makima.tools.selection import ToolExecutionGateway
from makima.plugins import PluginManifest
from makima.voice.gemini_live import DEFAULT_LIVE_MODEL

logger = logging.getLogger("makima.api.app")


class ChatRequest(BaseModel):
    """Payload for POST /api/chat."""
    prompt: Optional[str] = Field(default=None, description="User prompt string.")
    message: Optional[str] = Field(default=None, description="Alias for prompt.")
    messages: Optional[List[Dict[str, Any]]] = Field(default=None, description="Pre-existing conversation turns.")
    task: Optional[str] = Field(default="fast_chat", description="Task classification for ParetoRouter.")
    system_prompt: Optional[str] = Field(default=None, description="Custom system prompt.")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Sampling temperature.")
    max_turns: Optional[int] = Field(default=None, ge=1, le=100, description="Maximum execution turns.")
    session_id: Optional[str] = Field(default=None, max_length=160, description="Session to continue.")


class ChatResponse(BaseModel):
    """Response returned from POST /api/chat."""
    content: str
    turn_count: int
    tool_calls_executed: int
    completed: bool
    finish_reason: str
    model_used: str
    latency_ms: float
    messages: List[Dict[str, Any]]
    error: Optional[str] = None


class SettingsPatch(BaseModel):
    """Browser-safe UI settings; provider credentials are intentionally absent."""
    theme: Optional[Literal["dark", "light"]] = None
    persona: Optional[str] = None
    active_backend: Optional[str] = Field(default=None, max_length=160)
    language: Optional[Literal["en", "hi", "auto"]] = None
    max_turns: Optional[int] = Field(default=None, ge=1, le=100)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    response_density: Optional[Literal["compact", "balanced", "detailed"]] = None
    local_session_persistence: Optional[bool] = None
    read_aloud: Optional[bool] = None
    wake_word_enabled: Optional[bool] = None
    jarvis_mode: Optional[bool] = None
    wake_words: Optional[List[str]] = None
    followup_window_s: Optional[float] = Field(default=None, ge=1.0, le=30.0)
    auto_listen_on_start: Optional[bool] = None
    voice_name: Optional[str] = Field(default=None, max_length=64)
    voice_speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    ws_url: Optional[str] = Field(default=None, max_length=512)
    system_prompt: Optional[str] = Field(default=None, max_length=8000)
    thinking_mode: Optional[Literal["off", "auto", "on"]] = None


class ConnectorPatch(BaseModel):
    enabled: bool


class ConnectorConfigureRequest(BaseModel):
    credential: str = Field(..., max_length=1024)
    bridge_url: Optional[str] = Field(default=None, max_length=512)
    enabled: bool = True


class ToolEnabledPatch(BaseModel):
    enabled: bool


class PluginDiscoverRequest(BaseModel):
    url: str = Field(..., max_length=1024, description="Website URL or domain to probe")


class PluginInstallRequest(BaseModel):
    id: Optional[str] = None
    name: str
    kind: str = "openapi"
    description: str = ""
    icon: Optional[str] = None
    spec_url: Optional[str] = None
    spec_raw: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    auth_type: str = "none"
    token: Optional[str] = None
    header_name: Optional[str] = None


class PluginConfigureRequest(BaseModel):
    token: Optional[str] = Field(default=None, max_length=2048)
    header_name: Optional[str] = Field(default=None, max_length=128)
    env: Optional[Dict[str, str]] = None


class PluginToggleRequest(BaseModel):
    enabled: bool


class ClaudeImportRequest(BaseModel):
    config: Any


class SessionCreate(BaseModel):
    title: str = Field(default="New session", max_length=180)
    project_id: Optional[str] = Field(default=None, max_length=160)
    active_backend: str = Field(default="", max_length=160)


class SessionPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=180)
    project_id: Optional[str] = Field(default=None, max_length=160)
    active_backend: Optional[str] = Field(default=None, max_length=160)
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


def _ui_state_path() -> Path:
    """Return the user-scoped state path, overridable for tests and deployments."""
    configured = os.getenv("MAKIMA_UI_STATE_PATH")
    if configured:
        return Path(configured)
    return Path.home() / ".makima" / "state" / "ui_state.json"


def _session_db_path() -> Path:
    configured = os.getenv("MAKIMA_SESSION_DB_PATH")
    if configured:
        return Path(configured)
    return Path.home() / ".makima" / "state" / "sessions.sqlite3"


def _allowed_ui_origins() -> list[str]:
    """Return explicit local origins; provider credentials never cross this boundary."""
    configured = os.getenv("MAKIMA_UI_ALLOWED_ORIGINS", "")
    if configured.strip():
        return [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8000", "http://localhost:8000",
        "http://127.0.0.1:5173", "http://localhost:5173",
    ]


def _ui_dist_path() -> Path:
    configured = os.getenv("MAKIMA_UI_DIST_DIR", "")
    if configured.strip():
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "apps" / "chat_ui" / "dist"


def _read_ui_state(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Ignoring unreadable UI state at %s: %s", path, exc)
    return {}


def _write_ui_state(path: Path, state: Dict[str, Any]) -> None:
    """Persist UI-only state atomically without writing provider credentials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="ui_state_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _env_file_path() -> Path:
    configured = os.getenv("MAKIMA_ENV_FILE", "")
    if configured.strip():
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / ".env"


def _persist_env_key(key: str, value: str) -> None:
    """Saves a credential or setting to the persistent server-side .env file."""
    try:
        import dotenv
        env_path = _env_file_path()
        if not env_path.exists():
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch(mode=0o600)
        dotenv.set_key(str(env_path), key, value)
    except Exception as exc:
        logger.warning(f"Could not persist {key} to .env: {exc}")


def _remove_env_key(key: str) -> None:
    """Removes a credential from the persistent server-side .env file."""
    try:
        import dotenv
        env_path = _env_file_path()
        if env_path.exists():
            dotenv.unset_key(str(env_path), key)
    except Exception as exc:
        logger.warning(f"Could not remove {key} from .env: {exc}")


def create_app(
    engine: Optional[HermesAgentEngine] = None,
    registry: Optional[ToolRegistry] = None,
    ui_state_path: Optional[Path] = None,
    ui_dist_path: Optional[Path] = None,
    plugin_manager: Optional[Any] = None,
    session_db_path: Optional[Path] = None,
) -> FastAPI:
    """
    Factory function creating and configuring the Makima v2 FastAPI application.

    Args:
        engine: Optional pre-configured HermesAgentEngine instance.
        registry: Optional pre-configured ToolRegistry instance.

    Returns:
        Configured FastAPI application instance.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup sequence
        # On Windows, disable QuickEdit mode to prevent console mouse clicks from pausing the event loop
        if os.name == "nt":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                h_in = kernel32.GetStdHandle(-10)
                mode = ctypes.c_ulong()
                if kernel32.GetConsoleMode(h_in, ctypes.byref(mode)):
                    kernel32.SetConsoleMode(h_in, (mode.value & ~0x0040) | 0x0080)
            except Exception:
                pass
        if hasattr(app.state, "plugin_manager") and app.state.plugin_manager:
            try:
                await app.state.plugin_manager.load_all(app.state.registry)
            except Exception as exc:
                logger.warning(f"Error loading plugins on startup: {exc}")
        yield
        # Teardown sequence
        # 0. Cancel active background execution tasks
        if hasattr(app.state, "active_tasks") and app.state.active_tasks:
            for t in list(app.state.active_tasks):
                if not t.done():
                    t.cancel()

        # 1. Drain & close shared HTTP client pool
        try:
            await close_shared_client()
        except Exception as exc:
            logger.debug(f"Error closing shared HTTP pool: {exc}")

        # 2. Provider client pools
        if hasattr(app.state, "engine") and app.state.engine:
            if hasattr(app.state.engine, "router") and app.state.engine.router:
                if hasattr(app.state.engine.router, "close"):
                    try:
                        res = app.state.engine.router.close()
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as exc:
                        logger.debug(f"Error closing provider router: {exc}")

            # 3. SQLite WAL connections (EpisodicMemory.close())
            if hasattr(app.state.engine, "episodic_memory") and app.state.engine.episodic_memory:
                try:
                    await app.state.engine.episodic_memory.close()
                except Exception as exc:
                    logger.debug(f"Error closing episodic memory: {exc}")

        # 4. Browser child processes
        try:
            from makima.tools.browser import automation
            if getattr(automation, "_BROWSER_CONTROLLER", None) is not None:
                await automation._BROWSER_CONTROLLER.close()
        except Exception as exc:
            logger.debug(f"Error closing browser controller: {exc}")

        # 5. ConPTY terminal shells
        try:
            from makima.tools.terminal import conpty
            if getattr(conpty, "_conpty_manager_instance", None) is not None:
                conpty._conpty_manager_instance.close_all()
        except Exception as exc:
            logger.debug(f"Error closing ConPTY manager: {exc}")

        # 6. Plugin manager close
        if hasattr(app.state, "plugin_manager") and app.state.plugin_manager:
            try:
                await app.state.plugin_manager.close()
            except Exception as exc:
                logger.debug(f"Error closing plugin manager: {exc}")

    app = FastAPI(
        title="Makima v2 API",
        version=makima.__version__,
        description="Autonomous Multi-Platform AI Desktop Assistant API Server",
        lifespan=lifespan,
    )

    # State tracking. Only UI preferences and control-plane toggles are stored;
    # provider credentials remain in the server environment/configuration.
    app.state.start_time = time.time()
    app.state.engine = engine or build_engine()
    app.state.registry = registry or build_registry()
    app.state.plugin_manager = plugin_manager or build_plugin_manager()
    app.state.ui_state_path = ui_state_path or _ui_state_path()
    app.state.session_store = SessionStore(Path(session_db_path or os.getenv("MAKIMA_SESSION_DB_PATH", str(_session_db_path()))))
    app.state.allowed_ui_origins = _allowed_ui_origins()
    app.state.active_tasks = set()

    # Load persistent server-side .env if present
    env_path = _env_file_path()
    if env_path.exists():
        try:
            import dotenv
            dotenv.load_dotenv(str(env_path), override=False)
        except Exception as exc:
            logger.warning("Failed to load .env from %s: %s", env_path, exc)
    persisted = _read_ui_state(app.state.ui_state_path)
    app.state.ui_settings = {
        "theme": "dark",
        "persona": "Makima",
        "active_backend": "",
        "language": "en",
        "max_turns": 30,
        "temperature": 0.7,
        "response_density": "balanced",
        "local_session_persistence": True,
        "read_aloud": False,
        "wake_word_enabled": True,
        "jarvis_mode": True,
        "wake_words": ["makima", "hey makima", "jarvis", "suno makima"],
        "followup_window_s": 10.0,
        "auto_listen_on_start": True,
        "voice_name": "",
        "voice_speed": 1.0,
        "ws_url": "/ws",
        "system_prompt": "",
        "thinking_mode": "on",
    }
    persisted_settings = persisted.get("settings", {})
    if isinstance(persisted_settings, dict):
        app.state.ui_settings.update({
            key: persisted_settings[key]
            for key in app.state.ui_settings
            if key in persisted_settings
        })
    app_connectors = {
        "whatsapp": ("WhatsApp Web", "messaging", "phone", "Send and receive WhatsApp messages through the connected desktop session."),
        "github": ("GitHub", "developer", "token", "Repositories, pull requests, commits, issues, and code review."),
        "gdrive": ("Google Drive & Docs", "productivity", "oauth", "Search, read, and work with cloud documents and files."),
        "gmail": ("Gmail", "messaging", "oauth", "Search mail, draft replies, and prepare messages for approval."),
        "spotify": ("Spotify", "media", "oauth", "Search playlists and control playback on the connected player."),
        "slack": ("Slack", "messaging", "token", "Read channels and prepare channel or direct-message actions."),
        "notion": ("Notion", "productivity", "token", "Search notes, pages, databases, and workspace tasks."),
        "discord": ("Discord", "messaging", "token", "Read and prepare messages for connected Discord servers."),
        "youtube": ("YouTube Data", "media", "api_key", "Search videos, transcripts, and media references."),
        "figma": ("Figma", "developer", "token", "Inspect design files and export referenced assets."),
    }
    app.state.connectors = {
        key: {
            "id": key,
            "name": name,
            "category": category,
            "auth_type": auth_type,
            "enabled": False,
            "configured": False,
            "health": "not_configured",
            "description": desc,
            "supported": True,
            "detail": "Configure this integration in the Makima backend; secrets are never stored in the browser.",
            "last_checked": None,
        }
        for key, (name, category, auth_type, desc) in app_connectors.items()
    }
    for item in persisted.get("connectors", []):
        if isinstance(item, dict) and item.get("id") in app.state.connectors:
            app.state.connectors[item["id"]].update({
                "enabled": bool(item.get("enabled", True)),
                "configured": bool(item.get("configured", False)),
                "health": str(item.get("health", "unknown")),
                "last_checked": item.get("last_checked"),
                "detail": item.get("detail", ""),
            })

    # Auto-sync connectors state with active environment variables on startup
    if os.getenv("GITHUB_TOKEN"):
        app.state.connectors["github"]["configured"] = True
        app.state.connectors["github"]["health"] = "ready"
        if not app.state.connectors["github"].get("detail") or "Authorization is required" in app.state.connectors["github"]["detail"]:
            app.state.connectors["github"]["detail"] = "Connected via saved token."

    if os.getenv("WHATSAPP_PHONE"):
        app.state.connectors["whatsapp"]["configured"] = True
        app.state.connectors["whatsapp"]["health"] = "ready"
        app.state.connectors["whatsapp"]["detail"] = f"Paired with {os.getenv('WHATSAPP_PHONE')}."

    if os.getenv("DISCORD_BOT_TOKEN"):
        app.state.connectors["discord"]["configured"] = True
        app.state.connectors["discord"]["health"] = "ready"

    if os.getenv("TELEGRAM_BOT_TOKEN"):
        app.state.connectors["telegram"]["configured"] = True
        app.state.connectors["telegram"]["health"] = "ready"

    if os.getenv("SPOTIFY_CLIENT_ID"):
        app.state.connectors["spotify"]["configured"] = True
        app.state.connectors["spotify"]["health"] = "ready"

    app.state.disabled_tools = set(
        str(name) for name in persisted.get("disabled_tools", []) if isinstance(name, str)
    )

    def persist_control_plane() -> None:
        _write_ui_state(app.state.ui_state_path, {
            "settings": dict(app.state.ui_settings),
            "connectors": list(app.state.connectors.values()),
            "disabled_tools": sorted(app.state.disabled_tools),
        })

    # 1. Only the Vite development server is cross-origin; production is same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.allowed_ui_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 2. Include Real-time WebSocket Route
    app.include_router(ws_router)
    app.include_router(voice_ws_router)

    # -----------------------------------------------------------------------
    # REST Endpoints
    # -----------------------------------------------------------------------

    @app.get("/health", tags=["System"])
    async def health_check() -> Dict[str, Any]:
        """Returns server health, application version, and uptime in seconds."""
        uptime = round(time.time() - app.state.start_time, 2)
        return {
            "status": "ok",
            "version": makima.__version__,
            "uptime": uptime,
        }

    @app.get("/api/status", tags=["System"])
    async def system_status(request: Request) -> Dict[str, Any]:
        """Returns live hardware metrics and Pareto provider availability."""
        # System Hardware Telemetry via psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        mem_used_gb = round(mem.used / (1024**3), 2)
        mem_total_gb = round(mem.total / (1024**3), 2)

        sys_drive = os.getenv("SystemDrive", "C:")
        if not sys_drive.endswith("\\"):
            sys_drive += "\\"
        try:
            disk_pct = psutil.disk_usage(sys_drive).percent
        except Exception:
            disk_pct = 0.0

        # Provider Status from Engine Router
        eng: Optional[HermesAgentEngine] = request.app.state.engine
        router = getattr(eng, "router", None) if eng else None
        if router is None:
            router = ParetoRouter()
        
        if hasattr(router, "discover_live_models"):
            try:
                await router.discover_live_models()
            except Exception as exc:
                logger.debug("Live model discovery during status poll skipped: %s", exc)

        backends_status: Dict[str, Any] = {}

        for name, provider in router._providers.items():
            backend_cfg = provider.config
            is_avail = False
            if provider:
                avail_val = getattr(provider, "is_available", False)
                is_avail = avail_val() if callable(avail_val) else bool(avail_val)

            cb_state = "unknown"
            if provider and hasattr(provider, "circuit_breaker"):
                cb_state = provider.circuit_breaker.state.name

            cache_strat = "none"
            if provider and hasattr(provider, "cache_strategy"):
                cache_strat = getattr(provider.cache_strategy, "value", str(provider.cache_strategy))

            backends_status[name] = {
                "id": name,
                "adapter": backend_cfg.adapter,
                "model": backend_cfg.model,
                "available": is_avail,
                "status": "available" if is_avail else "unavailable",
                "quota_exhausted": cb_state == "OPEN",
                "circuit_breaker": cb_state,
                "latency_tier": backend_cfg.latency_tier,
                "cache_strategy": cache_strat,
            }

        return {
            "status": "operational",
            "system": {
                "cpu_percent": cpu_pct,
                "ram_percent": mem.percent,
                "ram_used_gb": mem_used_gb,
                "ram_total_gb": mem_total_gb,
                "disk_percent": disk_pct,
            },
            "providers": {
                "configured_backends": len(backends_status),
                "backends": backends_status,
                "cache": get_cache_manager().metrics.get_summary(),
            },
            "settings": request.app.state.ui_settings,
        }

    @app.get("/api/settings", tags=["Settings"])
    async def get_settings(request: Request) -> Dict[str, Any]:
        return {"settings": dict(request.app.state.ui_settings)}

    @app.get("/api/sessions", tags=["Sessions"])
    async def list_sessions(request: Request, q: str = "", include_archived: bool = False, limit: int = 100) -> Dict[str, Any]:
        return {"sessions": request.app.state.session_store.list_sessions(q, include_archived, limit)}

    @app.get("/api/sessions/search", tags=["Sessions"])
    async def search_sessions(request: Request, q: str = "", limit: int = 100) -> Dict[str, Any]:
        return {"sessions": request.app.state.session_store.list_sessions(q, True, limit)}

    @app.post("/api/sessions", tags=["Sessions"])
    async def create_session(request: Request, body: SessionCreate) -> Dict[str, Any]:
        return {"session": request.app.state.session_store.create_session(body.title, body.project_id, body.active_backend)}

    @app.get("/api/sessions/{session_id}/export", tags=["Sessions"])
    async def export_session(request: Request, session_id: str) -> Dict[str, Any]:
        exported = request.app.state.session_store.export_session(session_id)
        if exported is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        return exported

    @app.get("/api/sessions/{session_id}", tags=["Sessions"])
    async def get_session(request: Request, session_id: str) -> Dict[str, Any]:
        session = request.app.state.session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        return {"session": session}

    @app.patch("/api/sessions/{session_id}", tags=["Sessions"])
    async def patch_session(request: Request, session_id: str, body: SessionPatch) -> Dict[str, Any]:
        session = request.app.state.session_store.update_session(session_id, **body.model_dump(exclude_none=True))
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        return {"session": session}

    @app.delete("/api/sessions/{session_id}", tags=["Sessions"])
    async def delete_session(request: Request, session_id: str) -> Dict[str, Any]:
        if not request.app.state.session_store.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found.")
        return {"deleted": True, "id": session_id}


    @app.post("/api/settings", tags=["Settings"])
    async def update_settings(request: Request, patch: SettingsPatch) -> Dict[str, Any]:
        updates = patch.model_dump(exclude_none=True)
        request.app.state.ui_settings.update(updates)
        persist_control_plane()
        return {"settings": dict(request.app.state.ui_settings), "saved": True}

    @app.get("/api/connectors", tags=["Settings"])
    async def list_connectors(request: Request) -> Dict[str, Any]:
        return {"connectors": list(request.app.state.connectors.values())}

    @app.post("/api/connectors/{connector_id}", tags=["Settings"])
    async def update_connector(request: Request, connector_id: str, patch: ConnectorPatch) -> Dict[str, Any]:
        connector = request.app.state.connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'.")
        previous = connector["enabled"]
        try:
            connector["enabled"] = patch.enabled
            connector["health"] = "ready" if patch.enabled and connector.get("configured") else "not_configured" if patch.enabled else "disabled"
            connector["detail"] = "Connected and ready." if connector.get("configured") else "Enabled, but credentials or OAuth authorization are still required." if patch.enabled else "Integration disabled by user."
            connector["last_checked"] = time.time()
            persist_control_plane()
            return {"connector": dict(connector), "saved": True}
        except Exception:
            connector["enabled"] = previous
            raise

    @app.post("/api/connectors/{connector_id}/check", tags=["Settings"])
    async def check_connector(request: Request, connector_id: str) -> Dict[str, Any]:
        connector = request.app.state.connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'.")
        connector["last_checked"] = time.time()
        connector["health"] = "ready" if connector["enabled"] and connector.get("configured") else "not_configured" if connector["enabled"] else "disabled"
        connector["detail"] = (
            "Integration is connected and ready."
            if connector["enabled"] and connector.get("configured") else "Authorization is required before this integration can run."
            if connector["enabled"] else "Enable the integration before checking its health."
        )
        persist_control_plane()
        return {"connector": dict(connector), "ok": bool(connector["enabled"] and connector.get("configured"))}

    @app.post("/api/connectors/{connector_id}/configure", tags=["Settings"])
    async def configure_connector(request: Request, connector_id: str, body: ConnectorConfigureRequest) -> Dict[str, Any]:
        connector = request.app.state.connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'.")

        cred = body.credential.strip()
        if not cred:
            raise HTTPException(status_code=400, detail="Credential or token cannot be empty.")

        username_display = ""
        # Specific connector verification logic
        if connector_id == "github":
            try:
                client = await get_shared_client()
                gh_res = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {cred}",
                        "User-Agent": "Makima-Desktop-Assistant",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=8.0,
                )
                if gh_res.status_code == 200:
                    gh_data = gh_res.json()
                    login = gh_data.get("login", "")
                    username_display = f"@{login}"
                elif gh_res.status_code == 401:
                    raise HTTPException(status_code=400, detail="Invalid GitHub token (401 Unauthorized). Check permissions at github.com/settings/tokens.")
                else:
                    raise HTTPException(status_code=400, detail=f"GitHub API error ({gh_res.status_code}): {gh_res.text[:120]}")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not reach GitHub API to verify token: {exc}")

            os.environ["GITHUB_TOKEN"] = cred
            connector["detail"] = f"Connected as {username_display}."
            _persist_env_key("GITHUB_TOKEN", cred)

        elif connector_id == "whatsapp":
            os.environ["WHATSAPP_PHONE"] = cred
            _persist_env_key("WHATSAPP_PHONE", cred)
            if body.bridge_url:
                os.environ["WHATSAPP_BRIDGE_URL"] = body.bridge_url.strip()
                _persist_env_key("WHATSAPP_BRIDGE_URL", body.bridge_url.strip())
            connector["detail"] = f"Paired with {cred}."

        elif connector_id in ("discord", "telegram"):
            env_var = "DISCORD_BOT_TOKEN" if connector_id == "discord" else "TELEGRAM_BOT_TOKEN"
            os.environ[env_var] = cred
            _persist_env_key(env_var, cred)
            connector["detail"] = f"Token configured ({cred[:4]}...{cred[-4:] if len(cred) > 8 else ''})."

        elif connector_id == "spotify":
            os.environ["SPOTIFY_CLIENT_ID"] = cred
            _persist_env_key("SPOTIFY_CLIENT_ID", cred)
            connector["detail"] = "Client ID configured."

        else:
            connector["detail"] = "Credential configured."

        connector["enabled"] = True
        connector["configured"] = True
        connector["health"] = "ready"
        connector["last_checked"] = time.time()
        persist_control_plane()

        return {
            "ok": True,
            "connector": dict(connector),
            "message": f"Successfully authorized {connector['name']}!" + (f" ({username_display})" if username_display else ""),
        }

    @app.post("/api/connectors/{connector_id}/disconnect", tags=["Settings"])
    async def disconnect_connector(request: Request, connector_id: str) -> Dict[str, Any]:
        connector = request.app.state.connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"Unknown connector '{connector_id}'.")

        connector["configured"] = False
        connector["health"] = "not_configured"
        connector["detail"] = "Authorization is required before this integration can run."
        connector["last_checked"] = time.time()

        if connector_id == "github":
            os.environ.pop("GITHUB_TOKEN", None)
            _remove_env_key("GITHUB_TOKEN")
        elif connector_id == "whatsapp":
            os.environ.pop("WHATSAPP_PHONE", None)
            _remove_env_key("WHATSAPP_PHONE")
            os.environ.pop("WHATSAPP_BRIDGE_URL", None)
            _remove_env_key("WHATSAPP_BRIDGE_URL")
        elif connector_id == "discord":
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            _remove_env_key("DISCORD_BOT_TOKEN")
        elif connector_id == "telegram":
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            _remove_env_key("TELEGRAM_BOT_TOKEN")
        elif connector_id == "spotify":
            os.environ.pop("SPOTIFY_CLIENT_ID", None)
            _remove_env_key("SPOTIFY_CLIENT_ID")

        persist_control_plane()
        return {"ok": True, "connector": dict(connector), "message": f"{connector['name']} disconnected."}

    @app.get("/api/tools", tags=["Tools"])
    async def list_tools(request: Request) -> Dict[str, Any]:
        """Returns list of registered tools and their synthesized JSON schemas."""
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        # The UI must show disabled primary tools so they can be re-enabled, while
        # revealing their conditional fallbacks if the primary is currently disabled.
        all_tool_objects = reg.list_tools()
        disabled_names = set(request.app.state.disabled_tools)
        enabled_names = {
            tool.name for tool in all_tool_objects if tool.name not in disabled_names
        }
        visible_tool_objects = [
            tool for tool in all_tool_objects
            if not getattr(tool, "fallback_for", None)
            or str(tool.fallback_for) not in enabled_names
        ]
        schemas = [tool.to_schema(format="openai") for tool in visible_tool_objects]
        tools = []
        tool_objects = {tool.name: tool for tool in all_tool_objects}
        for schema in schemas:
            fn = schema.get("function", {})
            name = fn.get("name", "")
            tool = tool_objects.get(name)
            description = fn.get("description", "")
            text = f"{name} {description}".lower()
            is_destructive = any(word in text for word in ("delete", "remove", "send", "write", "execute", "shutdown"))
            tags = list(getattr(tool, "tags", []) or [])
            category = tags[0] if tags else ("system" if any(x in text for x in ("file", "desktop", "shell")) else "general")
            tools.append({
                **schema,
                "enabled": name not in request.app.state.disabled_tools,
                "category": category,
                "is_destructive": is_destructive,
                "live": True,
                "source": "native",
                "status": "disabled" if name in request.app.state.disabled_tools else "ready",
            })
        return {
            "tools": tools,
            "count": len(schemas),
        }

    @app.post("/api/tools/{tool_name}/enabled", tags=["Tools"])
    async def update_tool_enabled(request: Request, tool_name: str, patch: ToolEnabledPatch) -> Dict[str, Any]:
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        if tool_name not in reg.list_names():
            raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.")
        if patch.enabled:
            request.app.state.disabled_tools.discard(tool_name)
        else:
            request.app.state.disabled_tools.add(tool_name)
        persist_control_plane()
        return {"name": tool_name, "enabled": patch.enabled, "saved": True}

    @app.post("/api/tools/{tool_name}/check", tags=["Tools"])
    async def check_tool(request: Request, tool_name: str) -> Dict[str, Any]:
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        if tool_name not in reg.list_names():
            raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.")
        return {
            "name": tool_name,
            "ok": tool_name not in request.app.state.disabled_tools,
            "enabled": tool_name not in request.app.state.disabled_tools,
            "status": "ready" if tool_name not in request.app.state.disabled_tools else "disabled",
        }

    @app.get("/api/plugins", tags=["Plugins"])
    async def list_plugins(request: Request) -> Dict[str, Any]:
        """List all installed plugins (Local, MCP, OpenAPI actions)."""
        pm = request.app.state.plugin_manager
        return {
            "plugins": [m.to_dict() for m in pm.manifests()],
            "count": len(pm.manifests()),
        }

    @app.get("/api/plugins/catalog", tags=["Plugins"])
    async def get_catalog(url: Optional[str] = None) -> Dict[str, Any]:
        """Returns the curated 1-click marketplace catalog or fetches from a custom registry URL."""
        from makima.plugins import fetch_external_catalog, get_marketplace_catalog
        if url and url.strip():
            target_url = url.strip()
            try:
                items = await fetch_external_catalog(target_url)
                return {
                    "catalog": items,
                    "count": len(items),
                    "source": target_url,
                }
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to fetch registry from '{target_url}': {e}")

        items = get_marketplace_catalog()
        return {
            "catalog": items,
            "count": len(items),
            "source": "official",
        }

    @app.post("/api/plugins/discover", tags=["Plugins"])
    async def discover_plugin(body: PluginDiscoverRequest) -> Dict[str, Any]:
        """Probes a website or domain for ChatGPT plugin manifests or OpenAPI specifications."""
        from makima.plugins import discover_plugin_or_api
        res = await discover_plugin_or_api(body.url)
        return res.to_dict()

    @app.post("/api/plugins/install", tags=["Plugins"])
    async def install_plugin(request: Request, body: PluginInstallRequest) -> Dict[str, Any]:
        """Installs a plugin from discovery result, marketplace, or custom spec."""
        pm = request.app.state.plugin_manager
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        from makima.plugins import PluginManifest
        
        plugin_id = body.id or body.name.lower().replace(" ", "_")
        auth_cfg = {}
        if body.header_name:
            auth_cfg["header_name"] = body.header_name

        target_env = dict(body.env or {})
        token_to_save = body.token
        if "github" in (plugin_id + " " + body.name).lower():
            saved_token = token_to_save or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
            if saved_token:
                target_env["GITHUB_PERSONAL_ACCESS_TOKEN"] = saved_token
                target_env["GITHUB_TOKEN"] = saved_token
                if not token_to_save:
                    token_to_save = saved_token

        manifest = PluginManifest(
            id=plugin_id,
            name=body.name,
            kind=body.kind,
            enabled=True,
            trusted=True,
            description=body.description,
            icon=body.icon,
            spec_url=body.spec_url,
            spec_raw=body.spec_raw,
            base_url=body.base_url,
            command=body.command,
            args=tuple(body.args),
            env=target_env or None,
            auth_type=body.auth_type,
            auth_config=auth_cfg,
        )
        
        pm.save_manifest(manifest, secret_token=token_to_save)
        await pm.load_all(reg)
        refreshed = pm.get_manifest(plugin_id) or manifest
        return {
            "ok": True,
            "plugin": refreshed.to_dict(),
            "message": f"Plugin '{body.name}' installed and activated.",
        }

    @app.post("/api/plugins/{plugin_id}/toggle", tags=["Plugins"])
    async def toggle_plugin(request: Request, plugin_id: str, body: PluginToggleRequest) -> Dict[str, Any]:
        """Toggles enablement of an installed plugin."""
        pm = request.app.state.plugin_manager
        manifest = pm.get_manifest(plugin_id)
        if not manifest:
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found.")
        
        updated = PluginManifest(
            **{**manifest.__dict__, "enabled": body.enabled}
        )
        pm.save_manifest(updated)
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        await pm.load_all(reg)
        return {"ok": True, "plugin": updated.to_dict(), "enabled": body.enabled}

    @app.post("/api/plugins/{plugin_id}/configure", tags=["Plugins"])
    async def configure_plugin(request: Request, plugin_id: str, body: PluginConfigureRequest) -> Dict[str, Any]:
        """Updates credentials or environment variables for a plugin."""
        pm = request.app.state.plugin_manager
        manifest = pm.get_manifest(plugin_id)
        if not manifest:
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found.")

        updated_auth = dict(manifest.auth_config)
        if body.header_name:
            updated_auth["header_name"] = body.header_name
        
        updated_env = dict(manifest.env or {})
        if body.env:
            updated_env.update(body.env)

        updated = PluginManifest(
            **{**manifest.__dict__, "auth_config": updated_auth, "env": updated_env or None}
        )
        pm.save_manifest(updated, secret_token=body.token)
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        await pm.load_all(reg)
        return {"ok": True, "plugin": updated.to_dict(), "message": "Credentials updated successfully."}

    @app.delete("/api/plugins/{plugin_id}", tags=["Plugins"])
    async def uninstall_plugin(request: Request, plugin_id: str) -> Dict[str, Any]:
        """Uninstalls and removes a plugin."""
        pm = request.app.state.plugin_manager
        deleted = pm.delete_manifest(plugin_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found.")
        return {"ok": True, "message": f"Plugin '{plugin_id}' uninstalled."}

    @app.post("/api/plugins/import/claude", tags=["Plugins"])
    async def import_claude(request: Request, body: ClaudeImportRequest) -> Dict[str, Any]:
        """Imports MCP servers from a Claude Desktop config JSON."""
        from makima.plugins import import_claude_desktop_config
        manifests = import_claude_desktop_config(body.config)
        pm = request.app.state.plugin_manager
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        for m in manifests:
            pm.save_manifest(m)
        await pm.load_all(reg)
        return {
            "ok": True,
            "imported_count": len(manifests),
            "plugins": [m.to_dict() for m in manifests],
            "message": f"Successfully imported {len(manifests)} MCP server(s) from Claude Desktop config.",
        }

    @app.post("/api/plugins/sync", tags=["Plugins"])
    async def sync_plugins(request: Request) -> Dict[str, Any]:
        """Refreshes and synchronizes all active plugins and tools."""
        pm = request.app.state.plugin_manager
        reg: ToolRegistry = request.app.state.registry or get_registry(auto_discover=True)
        loaded = await pm.load_all(reg)
        return {"ok": True, "loaded": loaded}

    @app.get("/api/voice/capabilities", tags=["Voice"])
    async def voice_capabilities() -> Dict[str, Any]:
        from makima.config import get_settings
        configured_settings = get_settings()
        has_server_key = bool(os.getenv("GEMINI_API_KEY") or getattr(configured_settings, "gemini_api_key", None))
        return {
            "model": DEFAULT_LIVE_MODEL,
            "server_ready": has_server_key,
            "voices": ["Aoede", "Kore", "Puck", "Fenrir", "Charon"],
            "input_sample_rate_hz": 16000,
            "output_sample_rate_hz": 24000,
            "credentials_exposed": False,
        }

    @app.get("/api/diagnostics", tags=["System"])
    async def diagnostics(request: Request) -> Dict[str, Any]:
        """Return exportable, credential-free control-plane diagnostics."""
        tel = __import__("makima.core.telemetry", fromlist=["get_telemetry"]).get_telemetry()
        return {
            "health": await health_check(),
            "settings": dict(request.app.state.ui_settings),
            "connectors": list(request.app.state.connectors.values()),
            "disabled_tools": sorted(request.app.state.disabled_tools),
            "telemetry": tel.get_recent(100),
            "credentials_exposed": False,
        }

    @app.get("/api/telemetry", tags=["System"])
    async def get_telemetry_events(n: int = 50) -> Dict[str, Any]:
        """Returns the last N telemetry events from the in-memory ring buffer."""
        from makima.core.telemetry import get_telemetry
        tel = get_telemetry()
        events = tel.get_recent(max(1, min(500, n)))
        return {
            "events": events,
            "count": len(events),
            "buffer_total": tel.get_event_count(),
        }

    @app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
    async def chat_endpoint(request: Request, body: ChatRequest) -> ChatResponse:
        """Executes an autonomous Hermes turn or conversation run."""
        eng: Optional[HermesAgentEngine] = request.app.state.engine
        if eng is None:
            # Lazy initialize engine
            eng = build_engine(registry=request.app.state.registry)
            request.app.state.engine = eng

        effective_prompt = body.prompt or body.message
        if not effective_prompt and not body.messages:
            raise HTTPException(
                status_code=400,
                detail="Either 'prompt' or non-empty 'messages' must be provided.",
            )

        # Parse messages if provided
        parsed_messages: Optional[List[Message]] = None
        if body.messages:
            parsed_messages = [
                Message(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                    name=m.get("name"),
                    tool_call_id=m.get("tool_call_id"),
                )
                for m in body.messages
            ]
        elif body.session_id:
            if eng and eng.episodic_memory is not None:
                try:
                    episodic_msgs = await load_session_messages(eng, body.session_id)
                    if episodic_msgs:
                        parsed_messages = episodic_msgs
                except Exception as exc:
                    logger.debug("Episodic history load in /api/chat skipped: %s", exc)

            if parsed_messages is None:
                session = request.app.state.session_store.get_session(body.session_id)
                if session is None:
                    raise HTTPException(status_code=404, detail="Session not found.")
                parsed_messages = []
                for m in session.get("messages", []):
                    role = m.get("role", "user")
                    if role not in {"user", "assistant", "tool"}:
                        continue
                    msg_text = str(m.get("content") or "")
                    parsed_messages.append(Message(role=role, content=msg_text))
                    meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
                    if role == "assistant":
                        tool_trace = meta.get("tool_trace")
                        if isinstance(tool_trace, list) and tool_trace:
                            trace_str = "; ".join(str(t) for t in tool_trace[:8] if t)
                            if trace_str:
                                parsed_messages.append(Message(role="system", content=f"[System Telemetry: Prior turn executed {trace_str}]"))

        try:
            reg = request.app.state.registry or get_registry(auto_discover=True)
            # REST chat must enforce the same disabled-tool state and shared
            # execution guardrails as WebSocket chat and Gemini Live voice.
            execution_gateway = ToolExecutionGateway(
                reg,
                lambda: getattr(request.app.state, "disabled_tools", set()),
            )
            user_message_id = f"message_{uuid.uuid4().hex}"
            if body.session_id and effective_prompt:
                request.app.state.session_store.add_message(
                    body.session_id,
                    user_message_id,
                    "user",
                    effective_prompt,
                    metadata={"operation": "chat"},
                )
            result = await eng.run(
                prompt=effective_prompt,
                messages=parsed_messages,
                system_prompt=body.system_prompt,
                tools=execution_gateway,
                task=body.task,
                temperature=body.temperature,
                max_turns=body.max_turns,
                session_id=body.session_id,
            )

            if body.session_id:
                rest_tool_trace: list[str] = []
                for msg_item in result.messages:
                    if getattr(msg_item, "tool_calls", None):
                        for tc in msg_item.tool_calls or []:
                            tc_args = getattr(tc, "arguments", {}) or {}
                            key_parts = [
                                f"{k}='{str(tc_args[k]).strip()[:80]}'"
                                for k in ("action", "url", "query", "selector", "index")
                                if k in tc_args and tc_args[k] is not None
                            ]
                            rest_tool_trace.append(f"{tc.name}({', '.join(key_parts)})")
                request.app.state.session_store.add_message(
                    body.session_id,
                    f"assistant_{uuid.uuid4().hex}",
                    "assistant",
                    result.content,
                    parent_message_id=user_message_id,
                    metadata={
                        "model": result.model_used,
                        "finish_reason": result.finish_reason,
                        "tool_trace": rest_tool_trace[:12],
                    },
                )

            serialized_messages = [
                {
                    "role": m.role,
                    "content": m.content,
                    "name": m.name,
                    "tool_call_id": m.tool_call_id,
                    "tool_calls": [tc.model_dump() for tc in m.tool_calls] if m.tool_calls else None,
                }
                for m in result.messages
            ]

            return ChatResponse(
                content=result.content,
                turn_count=result.turn_count,
                tool_calls_executed=result.tool_calls_executed,
                completed=result.completed,
                finish_reason=result.finish_reason,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
                messages=serialized_messages,
                error=result.error,
            )
        except Exception as exc:
            logger.exception("Error executing chat request: %s", exc)
            raise HTTPException(status_code=500, detail="Makima could not complete this request.")

    # API and WebSocket routes above take precedence over the built command deck.
    # A missing frontend build must never block an API-only deployment.
    dist = (ui_dist_path or _ui_dist_path()).resolve()
    if os.getenv("MAKIMA_SERVE_UI", "1").lower() not in {"0", "false", "no"} and dist.is_dir() and (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="makima-ui")

    return app
