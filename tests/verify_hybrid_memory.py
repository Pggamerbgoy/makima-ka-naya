"""
Targeted test for Hybrid Memory Fusion (RRF + Time-Decay).
Verifies:
1. Concurrently querying VectorSearchEngine and EpisodicMemory (FTS5).
2. Proper RRF score calculation with exponential time-decay.
3. Deduplication and merging of items matching across semantic and keyword stores.
"""

import asyncio
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import BaseProvider, ProviderResponse
from makima.provider.router import ParetoCandidate, ParetoRouter


from unittest.mock import MagicMock

class MockProvider(BaseProvider):
    def __init__(self):
        mock_cfg = MagicMock()
        mock_cfg.model = "test-model"
        mock_cfg.is_available = True
        super().__init__(config=mock_cfg)
        self.captured_prompt = None

    async def generate(self, messages, system_prompt=None, **kwargs):
        self.captured_prompt = system_prompt
        return ProviderResponse(content="OK", finish_reason="stop", model="test-model")

    async def stream(self, *args, **kwargs):
        raise NotImplementedError()


class MockRouter(ParetoRouter):
    def __init__(self, prov):
        super().__init__()
        self.prov = prov

    def get_ranked_candidates(self, task="fast_chat"):
        return [
            ParetoCandidate(
                name="test",
                provider=self.prov,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=10.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task="fast_chat"):
        return self.prov


class StubVectorSearch:
    def __init__(self, hits):
        self.hits = hits

    async def search(self, prompt, top_k=5):
        return self.hits


class StubEpisodicMemory:
    def __init__(self, fts_results):
        self.fts_results = fts_results

    async def search_fts(self, query, session_id=None, limit=10):
        return self.fts_results

    async def get_recent_messages(self, session_id, limit=100):
        return []

    async def store_turn(self, *args, **kwargs):
        return 1


async def test_hybrid_rrf_scoring():
    print("[TEST] Testing Hybrid RRF Fusion + Time-Decay...")
    now = time.time()
    # Vector hit has semantic match
    vec_hits = [
        {"doc_id": "sess_1:10:user", "text": "Deploying docker container to prod", "distance": 0.15, "timestamp": now - 3600},
        {"doc_id": "vec_only_doc", "text": "Configuring python venv", "distance": 0.35, "timestamp": now - 7200},
    ]

    # FTS hit has exact keyword match on the same turn (sess_1:10:user) plus an FTS-only hit
    fts_hits = [
        {"id": 10, "session_id": "sess_1", "role": "user", "content": "Deploying docker container to prod", "timestamp": now - 3600, "rank": -5.2},
        {"id": 11, "session_id": "sess_1", "role": "assistant", "content": "Docker compose up -d was executed", "timestamp": now - 1800, "rank": -4.1},
    ]

    vector_store = StubVectorSearch(vec_hits)
    episodic_store = StubEpisodicMemory(fts_hits)
    prov = MockProvider()
    router = MockRouter(prov)

    engine = HermesAgentEngine(
        router=router,
        vector_search=vector_store,
        episodic_memory=episodic_store,
        memory_top_k=5,
    )

    result = await engine.run(prompt="docker container deploy", session_id="test_sess")
    assert result.completed is True
    assert prov.captured_prompt is not None

    prompt_str = prov.captured_prompt
    print("Captured prompt memory section:")
    for line in prompt_str.splitlines():
        if "Relevant Memory" in line or "sess_1:10" in line or "vec_only_doc" in line or "Docker compose" in line:
            print("  ", line)

    # 1. Check that memory block is injected
    assert "<memory>" in prompt_str
    assert "## Relevant Memory" in prompt_str

    # 2. Check that the merged item (both in vector and FTS) has the highest score
    # sess_1:10:user should appear before vec_only_doc
    pos_merged = prompt_str.find("sess_1:10:user")
    pos_vec_only = prompt_str.find("vec_only_doc")
    assert pos_merged != -1, "Merged item sess_1:10:user not found in prompt"
    assert pos_vec_only != -1, "vec_only_doc not found in prompt"
    assert pos_merged < pos_vec_only, "Merged item with both vector+FTS match should rank higher than single match"

    # 3. Check that FTS-only item is also recalled
    assert "Docker compose up -d" in prompt_str, "FTS-only item should be recalled via Hybrid fusion"

    print("  -> PASSED: Hybrid RRF Fusion correctly merges, scores, and injects memory!")


if __name__ == "__main__":
    asyncio.run(test_hybrid_rrf_scoring())
