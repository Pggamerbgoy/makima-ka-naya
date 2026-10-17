"""
Makima v2 — Provider Subsystem.
Zero-Cost Pareto Routing and Resilient Provider Adapters.
"""

from makima.provider.cache import (
    CacheStrategy,
    PromptCacheMetrics,
    UnifiedPromptCacheManager,
    canonicalize_tool_schemas,
    extract_cached_tokens,
    format_cached_messages,
    format_cached_tools,
    get_cache_manager,
    partition_system_prompt,
    resolve_cache_strategy,
)
from makima.provider.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)
from makima.provider.adapters.base import (
    BaseProvider,
    Message,
    ProviderResponse,
    StreamChunk,
    ToolCall,
)
from makima.provider.adapters.gemini import GeminiProvider
from makima.provider.adapters.openai_compatible import OpenAICompatibleProvider
from makima.provider.router import (
    ParetoCandidate,
    ParetoRouter,
    ProviderMetrics,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "BaseProvider",
    "Message",
    "ToolCall",
    "StreamChunk",
    "ProviderResponse",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "ParetoCandidate",
    "ParetoRouter",
    "ProviderMetrics",
    "CacheStrategy",
    "PromptCacheMetrics",
    "UnifiedPromptCacheManager",
    "canonicalize_tool_schemas",
    "extract_cached_tokens",
    "format_cached_messages",
    "format_cached_tools",
    "get_cache_manager",
    "partition_system_prompt",
    "resolve_cache_strategy",
]
