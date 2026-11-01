from typing import Dict, Any, List
from .state import StateMemory
from .episodic import EpisodicMemory
from .vector_search import VectorSearchEngine

class MemoryStore:
    """Unified façade orchestrating state profiles, SQLite episodic turns, and vector search."""
    def __init__(self):
        self.state = StateMemory()
        self.episodic = EpisodicMemory()
        self.vector = VectorSearchEngine()

    def get_full_context(self) -> str:
        return self.state.get_context()
