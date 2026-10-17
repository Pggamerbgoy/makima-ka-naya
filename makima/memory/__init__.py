"""
Makima v2 — Dual-Tier Memory Engine.
Tier 1: StateMemory (human-inspectable Markdown files MEMORY.md & USER.md for system prompt injection).
Tier 2: EpisodicMemory (async SQLite WAL database for multi-turn dialogue, tool calls, and FTS5 keyword retrieval).
Tier 3: VectorSearchEngine (fastembed + sqlite-vec on-device semantic search without PyTorch or GPU).
"""

from makima.memory.state import StateMemory, DEFAULT_USER_TEMPLATE, DEFAULT_MEMORY_TEMPLATE
from makima.memory.episodic import EpisodicMemory
from makima.memory.vector_search import VectorSearchEngine
from makima.memory.reflection import ImplicitPreferenceLearner

__all__ = [
    "StateMemory",
    "EpisodicMemory",
    "VectorSearchEngine",
    "ImplicitPreferenceLearner",
    "DEFAULT_USER_TEMPLATE",
    "DEFAULT_MEMORY_TEMPLATE",
]

