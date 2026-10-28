"""
Makima v2 — Dynamic Configuration Engine.
Architectural Pattern: Pydantic v2 + pydantic-settings with YAML loader and dynamic OS path resolution.
Zero-Hardcoding Guarantee: Fully dynamic paths (Path.home()), dynamic env key probing, and thread-safe singleton.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Ensure .env values are populated into os.environ for backend API key resolution
load_dotenv()

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# -----------------------------------------------------------------------------
# 1. Dynamic Path Resolver Utility
# -----------------------------------------------------------------------------

def resolve_path(path_val: str | Path, base_dir: Optional[Path] = None) -> Path:
    """
    Dynamically expands `~` to the current user's actual home directory
    and resolves relative paths without hardcoding platform paths.
    """
    p = Path(path_val).expanduser()
    if not p.is_absolute():
        base = base_dir or Path.cwd()
        p = (base / p).resolve()
    return p


# -----------------------------------------------------------------------------
# 2. Schema Sub-Models
# -----------------------------------------------------------------------------

class AppConfig(BaseModel):
    name: str = "Makima"
    version: str = "2.0.0"
    env: str = "development"
    data_dir: str = "~/.makima"
    log_level: str = "INFO"


class CircuitBreakerConfig(BaseModel):
    max_failures: int = 3
    cooldown_seconds: float = 30.0
    jitter: bool = True


class BackendConfig(BaseModel):
    adapter: str
    model: str
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None
    latency_tier: str = "standard"
    context_limit: int = 286000

    @property
    def api_key(self) -> Optional[str]:
        """Dynamically fetch the API key from environment if configured."""
        if self.api_key_env:
            raw = os.getenv(self.api_key_env)
            if raw and "," in raw:
                keys = [k.strip() for k in raw.split(",") if k.strip()]
                return keys[0] if keys else None
            return raw
        return None

    @property
    def is_available(self) -> bool:
        """
        Check if the backend is currently usable without requiring paid keys.
        Ollama is local and available if running. Others check if env var is non-empty.
        """
        if self.adapter == "ollama":
            return True
        return bool(self.api_key)


class ProvidersConfig(BaseModel):
    default: str = "auto"
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    cascades: Dict[str, List[str]] = Field(default_factory=lambda: {
        "fast_chat": ["groq", "gemini", "openrouter_free", "ollama"],
        "code": ["ollama", "groq", "openrouter_free", "gemini"],
        "deep_reasoning": ["gemini", "openrouter_free", "ollama"],
        "vision": ["gemini"],
        "voice": ["gemini_live"],
        "offline": ["ollama"],
    })
    backends: Dict[str, BackendConfig] = Field(default_factory=dict)


class GatewaySecurityConfig(BaseModel):
    allow_all_users: bool = False
    allowlist_user_ids: List[str] = Field(default_factory=list)
    pairing_code_enabled: bool = True


class TelegramPlatformConfig(BaseModel):
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    require_mention_in_groups: bool = True


class DiscordPlatformConfig(BaseModel):
    enabled: bool = False
    token_env: str = "DISCORD_BOT_TOKEN"
    voice_enabled: bool = True


class WhatsAppPlatformConfig(BaseModel):
    enabled: bool = False
    session_dir: str = "~/.makima/whatsapp_session"


class GatewayPlatformsConfig(BaseModel):
    telegram: TelegramPlatformConfig = Field(default_factory=TelegramPlatformConfig)
    discord: DiscordPlatformConfig = Field(default_factory=DiscordPlatformConfig)
    whatsapp: WhatsAppPlatformConfig = Field(default_factory=WhatsAppPlatformConfig)


class GatewayConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    security: GatewaySecurityConfig = Field(default_factory=GatewaySecurityConfig)
    platforms: GatewayPlatformsConfig = Field(default_factory=GatewayPlatformsConfig)


class VectorSearchConfig(BaseModel):
    enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    dimension: int = 384


class MemoryConfig(BaseModel):
    state_dir: str = "~/.makima/state"
    sqlite_path: str = "~/.makima/state/history.db"
    fts_enabled: bool = True
    vector_search: VectorSearchConfig = Field(default_factory=VectorSearchConfig)


class SkillsConfig(BaseModel):
    directory: str = "~/.makima/skills"
    auto_synthesize: bool = True


class SandboxToolsConfig(BaseModel):
    mode: str = "local_clamped"  # "local_clamped" or "docker"
    workspace_dir: str = "~/.makima/workspace"
    command_timeout_seconds: int = 45
    block_dangerous_commands: bool = True


class BrowserToolsConfig(BaseModel):
    headless: bool = False
    stealth: bool = True
    cdp_endpoint: str = "http://localhost:9222"


class ConcurrencyToolsConfig(BaseModel):
    enabled: bool = True
    max_concurrency: int = 8
    parallel_safe_tags: List[str] = Field(default_factory=lambda: [
        "search", "read", "info", "system_info", "stats", "telemetry",
        "web", "internet", "research", "query", "memory", "filesystem_read",
    ])
    mutating_tags: List[str] = Field(default_factory=lambda: [
        "desktop", "input", "write", "delete", "control", "exec", "terminal",
        "kill", "window", "mouse", "keyboard", "uia", "mutating",
    ])


class ToolSelectionConfig(BaseModel):
    enabled: bool = True
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Keep the full current tool catalogue visible (currently ~68 tools).
    # Semantic narrowing activates only for larger installations; otherwise the
    # model cannot select a feature whose schema was hidden before the request.
    max_candidates: int = Field(default=96, ge=1)
    minimum_candidates: int = Field(default=24, ge=1)
    minimum_similarity: float = Field(default=0.20, ge=-1.0, le=1.0)


class ToolsConfig(BaseModel):
    sandbox: SandboxToolsConfig = Field(default_factory=SandboxToolsConfig)
    browser: BrowserToolsConfig = Field(default_factory=BrowserToolsConfig)
    concurrency: ConcurrencyToolsConfig = Field(default_factory=ConcurrencyToolsConfig)
    selection: ToolSelectionConfig = Field(default_factory=ToolSelectionConfig)


class SoundDeviceVoiceConfig(BaseModel):
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    channels: int = 1


class VoiceConfig(BaseModel):
    engine: str = "gemini_live"  # Exclusively Gemini 3.8 Live native voice (No TTS)
    model: str = "gemini-2.0-flash-exp"
    voice_name: str = "Aoede"  # Aoede, Charon, Fenrir, Kore, Puck
    jarvis_mode: bool = True
    wake_words: List[str] = Field(default_factory=lambda: ["makima", "hey makima", "jarvis", "suno makima"])
    followup_window_s: float = 10.0
    sounddevice: SoundDeviceVoiceConfig = Field(default_factory=SoundDeviceVoiceConfig)



# -----------------------------------------------------------------------------
# 3. Master Settings Container
# -----------------------------------------------------------------------------

class MakimaSettings(BaseSettings):
    """
    Master dynamic configuration container for Makima v2.
    Loads values hierarchically:
      1. Default Pydantic field values
      2. configs/settings.yaml
      3. .env file
      4. Environment variables prefixed with MAKIMA_ (e.g. MAKIMA_APP__ENV=production)
    """
    app: AppConfig = Field(default_factory=AppConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    # Dynamic HTTP Pool & Tool Execution Limits
    http_max_keepalive: int = 50
    http_max_connections: int = 100
    http_timeout: float = 30.0
    tool_timeout: float = 45.0
    max_tool_output_chars: int = 16000

    model_config = SettingsConfigDict(
        env_prefix="MAKIMA_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (env_settings, dotenv_settings, init_settings)

    # Dynamic Path Accessors
    @property
    def data_dir_path(self) -> Path:
        return resolve_path(self.app.data_dir)

    @property
    def workspace_dir_path(self) -> Path:
        return resolve_path(self.tools.sandbox.workspace_dir)

    @property
    def state_dir_path(self) -> Path:
        return resolve_path(self.memory.state_dir)

    @property
    def sqlite_db_path(self) -> Path:
        return resolve_path(self.memory.sqlite_path)

    @property
    def skills_dir_path(self) -> Path:
        return resolve_path(self.skills.directory)

    @property
    def whatsapp_session_path(self) -> Path:
        return resolve_path(self.gateway.platforms.whatsapp.session_dir)

    def ensure_directories(self) -> None:
        """
        Creates all essential directories safely on the host system without
        relying on hardcoded Windows or Linux absolute paths.
        """
        dirs = [
            self.data_dir_path,
            self.workspace_dir_path,
            self.state_dir_path,
            self.sqlite_db_path.parent,
            self.skills_dir_path,
            self.whatsapp_session_path,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def get_backend(self, name: str) -> Optional[BackendConfig]:
        """Retrieve backend configuration by identifier name."""
        return self.providers.backends.get(name)

    def get_available_backends(self) -> List[str]:
        """Return list of backend names that are currently usable."""
        return [name for name, b in self.providers.backends.items() if b.is_available]

    def get_active_credentials(self) -> Dict[str, bool]:
        """Scan and report presence of API keys across all configured backends."""
        active = {}
        for name, b in self.providers.backends.items():
            if b.api_key_env:
                active[b.api_key_env] = bool(os.getenv(b.api_key_env))
        return active


# -----------------------------------------------------------------------------
# 4. Thread-Safe Global Settings Accessor
# -----------------------------------------------------------------------------

_settings_lock = threading.Lock()
_cached_settings: Optional[MakimaSettings] = None


def load_raw_yaml(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load configuration dictionary from YAML file if available."""
    if config_path is None:
        # Check standard default locations
        candidates = [
            Path("configs/settings.yaml"),
            Path(__file__).resolve().parent.parent / "configs" / "settings.yaml",
            Path.home() / ".makima" / "settings.yaml",
        ]
        for c in candidates:
            if c.is_file():
                config_path = c
                break

    if config_path and Path(config_path).is_file():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or {}
    return {}


def get_settings(config_path: Optional[Path | str] = None, force_reload: bool = False) -> MakimaSettings:
    """
    Thread-safe accessor returning the active MakimaSettings singleton.
    Merges configs/settings.yaml with environment variables and .env.
    """
    global _cached_settings

    if _cached_settings is not None and not force_reload:
        return _cached_settings

    with _settings_lock:
        if _cached_settings is not None and not force_reload:
            return _cached_settings

        raw_yaml = load_raw_yaml(config_path)
        settings = MakimaSettings(**raw_yaml)
        _cached_settings = settings
        return _cached_settings
