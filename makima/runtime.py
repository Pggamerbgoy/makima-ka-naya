"""Shared Makima runtime construction and session context helpers."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from makima.config import MakimaSettings, get_settings
from makima.core.engine import HermesAgentEngine
from makima.memory import EpisodicMemory, StateMemory, VectorSearchEngine
from makima.plugins import PluginManager
from makima.skills.loader import SkillsLoader
from makima.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger("makima.runtime")


def build_engine(
    settings: Optional[MakimaSettings] = None,
    registry: Optional[ToolRegistry] = None,
) -> HermesAgentEngine:
    """Build one fully-wired engine for all local and gateway entry points."""
    cfg = settings or get_settings()
    cfg.ensure_directories()

    episodic = EpisodicMemory(
        db_path=cfg.sqlite_db_path,
        fts_enabled=cfg.memory.fts_enabled,
    )
    state = StateMemory(data_dir=cfg.data_dir_path)
    vector = None
    if cfg.memory.vector_search.enabled:
        vector = VectorSearchEngine(
            model_name=cfg.memory.vector_search.embedding_model,
        )
    skills = SkillsLoader(skills_dir=cfg.skills_dir_path)

    # Keep the registry argument available for callers that need to control the
    # exposed tool set; the engine itself only needs the memory/skills services.
    _ = registry
    return HermesAgentEngine(
        episodic_memory=episodic,
        vector_search=vector,
        state_memory=state,
        skills_loader=skills,
    )


async def load_session_messages(
    engine: HermesAgentEngine,
    session_id: Optional[str],
    limit: int = 100,
) -> List[Any]:
    """Load bounded episodic history for a session, degrading safely if unavailable."""
    if not session_id or engine.episodic_memory is None:
        return []
    try:
        return await engine.episodic_memory.get_recent_messages(session_id, limit=limit)
    except Exception as exc:
        logger.debug("Session history unavailable for %s: %s", session_id, exc)
        return []


def build_registry() -> ToolRegistry:
    """Return the shared discovered registry used by production entry points."""
    registry = get_registry(auto_discover=True)
    settings = get_settings()
    PluginManager(settings.data_dir_path / "plugins").load_local(registry)
    return registry


def build_plugin_manager(settings: Optional[MakimaSettings] = None) -> PluginManager:
    cfg = settings or get_settings()
    return PluginManager(cfg.data_dir_path / "plugins")
