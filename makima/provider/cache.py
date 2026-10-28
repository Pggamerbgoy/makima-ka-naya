"""
Makima v2 — Unified Multi-Provider KV & Prompt Cache Coordinator.
Architectural Pattern: Universal LLM Prompt Caching Layer bridging:
  1. Google GenAI Explicit Context Caching (client.aio.caches.create, cachedContents/*)
  2. Anthropic & OpenRouter Explicit Ephemeral Breakpoints (cache_control: {"type": "ephemeral"})
  3. OpenAI, DeepSeek, Groq, Cerebras, DashScope, & local Ollama Automatic KV Prefix Caching
Zero-Duplication Guarantee: Single canonical normalization, schema canonicalization, and token usage extraction.
"""

from __future__ import annotations

from collections import OrderedDict
from enum import Enum
import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from makima.provider.adapters.base import Message

logger = logging.getLogger("makima.provider.cache")


class CacheStrategy(str, Enum):
    """Execution strategy for context and KV prompt caching."""
    EXPLICIT_GENAI = "explicit_genai"
    EXPLICIT_CACHE_CONTROL = "explicit_cache_control"
    AUTOMATIC_PREFIX = "automatic_prefix"
    DISABLED = "disabled"


def resolve_cache_strategy(
    adapter: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> CacheStrategy:
    """
    Deterministically resolves the optimal caching strategy for any model or API endpoint.

    Classification matrix:
      - adapter == 'gemini': Google GenAI Explicit Context Caching (CachedContent API)
      - adapter == 'anthropic' or base_url containing 'anthropic.com':
          Anthropic Ephemeral Cache Control breakpoints on static prompt & tools
      - base_url containing 'openrouter.ai':
          - Claude/Anthropic/Qwen models: Anthropic-style explicit cache_control breakpoints
          - DeepSeek models & others: Automatic KV Prefix Caching at Byte 0
      - base_url containing 'openai', 'deepseek', 'groq', 'cerebras', 'dashscope', 'ollama',
          or localhost: Automatic KV Prefix Caching at Byte 0
      - default for openai-compatible: AUTOMATIC_PREFIX (canonical sorting & deterministic layout)
    """
    adapter_norm = (adapter or "").strip().lower()
    if adapter_norm == "gemini":
        return CacheStrategy.EXPLICIT_GENAI

    base = (base_url or "").strip().lower()
    m_name = (model or "").strip().lower()

    if adapter_norm == "anthropic" or "anthropic.com" in base:
        return CacheStrategy.EXPLICIT_CACHE_CONTROL

    if "openrouter.ai" in base:
        # DeepSeek on OpenRouter uses automatic prompt prefix caching (matching native DeepSeek)
        if "deepseek" in m_name:
            return CacheStrategy.AUTOMATIC_PREFIX
        # Claude and Qwen support explicit cache_control breakpoints on OpenRouter
        if any(kw in m_name for kw in ("claude", "anthropic", "sonnet", "haiku", "opus", "qwen")):
            return CacheStrategy.EXPLICIT_CACHE_CONTROL
        return CacheStrategy.AUTOMATIC_PREFIX

    if any(endpoint in base for endpoint in (
        "api.openai.com",
        "api.deepseek.com",
        "api.groq.com",
        "api.cerebras.ai",
        "dashscope",
        "aliyuncs.com",
        "ollama",
        "localhost",
        "127.0.0.1",
    )):
        return CacheStrategy.AUTOMATIC_PREFIX

    if adapter_norm in ("openai", "ollama"):
        return CacheStrategy.AUTOMATIC_PREFIX

    return CacheStrategy.DISABLED


def _canonicalize_dict(val: Any) -> Any:
    """Recursively sorts dictionary keys so JSON serialization is deterministic down to the byte."""
    if isinstance(val, dict):
        return {k: _canonicalize_dict(v) for k, v in sorted(val.items())}
    if isinstance(val, list):
        return [_canonicalize_dict(x) for x in val]
    return val


def canonicalize_tool_schemas(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """
    Canonicalizes tool declarations for 100% KV Cache prefix stability:
      1. Deduplicates tools by function name.
      2. Alphabetically sorts tools by function name.
      3. Recursively normalizes nested property/parameter schema dictionaries.
    Guarantees zero byte-level divergence across turns and sessions.
    """
    if not tools:
        return None

    seen_names = set()
    deduped_tools: List[Dict[str, Any]] = []

    for t in tools:
        if not isinstance(t, dict):
            continue
        # Extract tool name across both direct schema and OpenAI nested function schemas
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        name = fn.get("name") if isinstance(fn, dict) else str(t.get("name", ""))

        if name:
            if name in seen_names:
                continue
            seen_names.add(name)

        if "type" in t and "function" in t:
            clean_entry = {
                "type": t["type"],
                "function": _canonicalize_dict(t["function"]),
            }
        elif "name" in t:
            clean_entry = {
                "type": "function",
                "function": _canonicalize_dict(t),
            }
        else:
            clean_entry = _canonicalize_dict(t)

        deduped_tools.append(clean_entry)

    if not deduped_tools:
        return None

    # Alphabetical sorting by tool function name
    deduped_tools.sort(
        key=lambda s: (
            s.get("function", {}).get("name", "")
            if isinstance(s.get("function"), dict)
            else str(s.get("name", ""))
        )
    )
    return deduped_tools


def partition_system_prompt(system_prompt: Optional[str]) -> Tuple[str, str]:
    """
    Partitions a system prompt into:
      - static_prefix: Immutable base instructions, persona rules, and durable system directives.
      - dynamic_suffix: Ephemeral per-turn data (e.g. active browser DOM state, query-dependent memory, skills).

    Keeps the immutable prefix strictly at Byte 0 so that:
      1. Anthropic / OpenRouter explicit `cache_control` breakpoints are placed ONLY on the immutable base.
      2. OpenAI, Groq, DeepSeek, and Gemini KV prefix caches achieve maximum byte-0 hit rates.
    """
    if not system_prompt:
        return "", ""

    # Check for active dynamic browser context
    if "<active_browser_state>" in system_prompt:
        parts = system_prompt.split("<active_browser_state>", 1)
        prefix = parts[0].rstrip()
        if prefix.endswith("---"):
            prefix = prefix[:-3].rstrip()
        suffix = "<active_browser_state>" + parts[1]
        return prefix, suffix

    dynamic_markers = (
        "<memory>",
        "<memory\n",
        "<skills>",
        "<skills\n",
        "## Available Skills",
        "## Active Skills",
        "<active",
        "<dynamic",
        "<turn_",
        "<ephemeral",
    )

    # Check for dynamic section dividers (may contain multiple '---' sections, e.g. base + memory + skills)
    if "\n\n---\n\n" in system_prompt:
        sections = system_prompt.split("\n\n---\n\n")
        split_idx = -1
        for idx in range(1, len(sections)):
            sec_strip = sections[idx].lstrip()
            if any(sec_strip.startswith(m) or m in sections[idx] for m in dynamic_markers):
                split_idx = idx
                break

        if split_idx != -1:
            prefix = "\n\n---\n\n".join(sections[:split_idx]).rstrip()
            suffix = "\n\n---\n\n".join(sections[split_idx:]).lstrip()
            return prefix, suffix

    # Direct marker search if no explicit '---' divider was used
    for marker in ("<memory>", "<skills>", "<dynamic_context>", "<ephemeral_context>"):
        if marker in system_prompt:
            prefix, suffix = system_prompt.split(marker, 1)
            prefix = prefix.rstrip()
            if prefix.endswith("---"):
                prefix = prefix[:-3].rstrip()
            return prefix, marker + suffix

    return system_prompt, ""


def format_cached_messages(
    messages: List[Message],
    system_prompt: Optional[str] = None,
    strategy: CacheStrategy = CacheStrategy.AUTOMATIC_PREFIX,
) -> List[Dict[str, Any]]:
    """
    Formats canonical Message models into OpenAI-compatible chat messages with prompt cache alignment.
    For EXPLICIT_CACHE_CONTROL (Anthropic/OpenRouter):
      Attaches `cache_control: {"type": "ephemeral"}` to the static system instruction block.
    For AUTOMATIC_PREFIX (OpenAI/DeepSeek/Groq/Ollama):
      Places the static system prompt at message index 0 so token sequence is identical across calls.
    """
    formatted: List[Dict[str, Any]] = []

    if system_prompt:
        if strategy == CacheStrategy.EXPLICIT_CACHE_CONTROL:
            static_prefix, dynamic_suffix = partition_system_prompt(system_prompt)
            content_blocks: List[Dict[str, Any]] = [
                {
                    "type": "text",
                    "text": static_prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            if dynamic_suffix:
                content_blocks.append({
                    "type": "text",
                    "text": dynamic_suffix,
                })
            formatted.append({
                "role": "system",
                "content": content_blocks,
            })
        else:
            formatted.append({
                "role": "system",
                "content": system_prompt,
            })

    for msg in messages:
        entry: Dict[str, Any] = {
            "role": msg.role,
            "content": msg.content or "",
        }

        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": (
                            json.dumps(tc.arguments, sort_keys=True)
                            if isinstance(tc.arguments, dict)
                            else str(tc.arguments)
                        ),
                    },
                }
                for tc in msg.tool_calls
            ]

        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id

        if msg.name:
            entry["name"] = msg.name

        formatted.append(entry)

    return formatted


def format_cached_tools(
    tools: Optional[List[Dict[str, Any]]],
    strategy: CacheStrategy = CacheStrategy.AUTOMATIC_PREFIX,
) -> Optional[List[Dict[str, Any]]]:
    """
    Applies canonical sorting and attaches explicit ephemeral cache control breakpoints when supported.
    """
    canonical_tools = canonicalize_tool_schemas(tools)
    if not canonical_tools:
        return None

    if strategy == CacheStrategy.EXPLICIT_CACHE_CONTROL and canonical_tools:
        # In Anthropic / OpenRouter, placing cache_control on the LAST tool caches the entire tool catalogue.
        tools_with_cache = [dict(t) for t in canonical_tools]
        last_tool = dict(tools_with_cache[-1])
        last_tool["cache_control"] = {"type": "ephemeral"}
        tools_with_cache[-1] = last_tool
        return tools_with_cache

    return canonical_tools


def extract_cached_tokens(response_or_usage: Any) -> int:
    """
    Robust universal extractor for cached token metrics across all model vendors:
      - OpenAI / Groq / Cerebras: usage.prompt_tokens_details.cached_tokens
      - DeepSeek: usage.prompt_cache_hit_tokens
      - Anthropic / OpenRouter: usage.cache_read_input_tokens
      - Google GenAI: usage_metadata.cached_content_token_count
      - Generic dicts: usage['cached_tokens'] or usage['prompt_tokens_details']['cached_tokens']
    Works seamlessly whether passed a full response, a usage object, a dict, or a mock.
    Never raises an exception; gracefully returns 0 on unknown structures.
    """
    if response_or_usage is None:
        return 0

    # 1. Direct scalar passed
    if isinstance(response_or_usage, (int, float)):
        return int(response_or_usage)

    def _extract_from_container(target: Any) -> Optional[int]:
        if target is None:
            return None

        # Dict handling
        if isinstance(target, dict):
            ptd = target.get("prompt_tokens_details")
            if isinstance(ptd, dict) and "cached_tokens" in ptd:
                val = ptd["cached_tokens"]
                if isinstance(val, (int, float, str)):
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        pass

            for key in ("prompt_cache_hit_tokens", "cache_read_input_tokens", "cached_tokens", "cached_content_token_count"):
                val = target.get(key)
                if isinstance(val, (int, float, str)):
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        pass
            return None

        # Object attribute handling
        # A. prompt_tokens_details.cached_tokens (OpenAI, Groq, Cerebras)
        try:
            ptd = getattr(target, "prompt_tokens_details", None)
            if ptd is not None:
                c_val = ptd.get("cached_tokens") if isinstance(ptd, dict) else getattr(ptd, "cached_tokens", None)
                if isinstance(c_val, (int, float, str)):
                    return int(c_val)
        except Exception:
            pass

        # B. cached_content_token_count (Google GenAI)
        try:
            c_val = getattr(target, "cached_content_token_count", None)
            if isinstance(c_val, (int, float, str)):
                return int(c_val)
        except Exception:
            pass

        # C. DeepSeek / OpenRouter / Anthropic flat metrics
        for attr in ("prompt_cache_hit_tokens", "cache_read_input_tokens", "cached_tokens"):
            try:
                c_val = getattr(target, attr, None)
                if isinstance(c_val, (int, float, str)):
                    return int(c_val)
            except Exception:
                pass

        return None

    # Step 1: Check target directly
    direct_res = _extract_from_container(response_or_usage)
    if direct_res is not None:
        return direct_res

    # Step 2: Check target.usage (OpenAI / standard response)
    try:
        if hasattr(response_or_usage, "usage"):
            usage_res = _extract_from_container(getattr(response_or_usage, "usage", None))
            if usage_res is not None:
                return usage_res
    except Exception:
        pass

    # Step 3: Check target.usage_metadata (Google GenAI response)
    try:
        if hasattr(response_or_usage, "usage_metadata"):
            meta_res = _extract_from_container(getattr(response_or_usage, "usage_metadata", None))
            if meta_res is not None:
                return meta_res
    except Exception:
        pass

    return 0


class PromptCacheMetrics:
    """Thread-safe telemetry accumulator for tracking prompt caching efficiency and token savings."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.cache_hits: int = 0
        self.total_prompt_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.by_model: Dict[str, Dict[str, int]] = {}

    def record_turn(self, model: str, prompt_tokens: int, cached_tokens: int) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_prompt_tokens += max(0, prompt_tokens)
            safe_cached = max(0, cached_tokens)
            self.total_cached_tokens += safe_cached
            if safe_cached > 0:
                self.cache_hits += 1

            m_key = model or "unknown"
            if m_key not in self.by_model:
                self.by_model[m_key] = {
                    "requests": 0,
                    "cache_hits": 0,
                    "prompt_tokens": 0,
                    "cached_tokens": 0,
                }
            self.by_model[m_key]["requests"] += 1
            self.by_model[m_key]["prompt_tokens"] += max(0, prompt_tokens)
            self.by_model[m_key]["cached_tokens"] += safe_cached
            if safe_cached > 0:
                self.by_model[m_key]["cache_hits"] += 1

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            hit_rate = (self.cache_hits / self.total_requests) if self.total_requests > 0 else 0.0
            # Token accounting: in OpenAI and Gemini API usage conventions, `prompt_tokens`
            # represents the total input tokens (which already subsumes cached tokens).
            # Avoid double-counting cached tokens in the denominator.
            if self.total_prompt_tokens > 0:
                savings_pct = min(100.0, (self.total_cached_tokens / self.total_prompt_tokens) * 100.0)
            else:
                savings_pct = 0.0
            return {
                "total_requests": self.total_requests,
                "cache_hits": self.cache_hits,
                "cache_hit_rate": round(hit_rate, 4),
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_cached_tokens": self.total_cached_tokens,
                "estimated_token_savings_pct": round(savings_pct, 2),
                "by_model": dict(self.by_model),
            }


class UnifiedPromptCacheManager:
    """
    Central Coordinator for Multi-Provider Prompt & Context Caching.
    Manages formatting, canonicalization, in-memory bounded LRU serialization caches, and metrics.
    """

    _instance: Optional[UnifiedPromptCacheManager] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> UnifiedPromptCacheManager:
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self, max_tool_cache_size: int = 256):
        self.metrics = PromptCacheMetrics()
        self._tool_cache_lock = threading.Lock()
        self._max_tool_cache_size = max_tool_cache_size
        self._tool_format_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()

    def get_strategy(
        self,
        adapter: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> CacheStrategy:
        return resolve_cache_strategy(adapter=adapter, base_url=base_url, model=model)

    def format_messages(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        strategy: CacheStrategy = CacheStrategy.AUTOMATIC_PREFIX,
    ) -> List[Dict[str, Any]]:
        return format_cached_messages(
            messages=messages,
            system_prompt=system_prompt,
            strategy=strategy,
        )

    def format_tools(
        self,
        tools: Optional[List[Dict[str, Any]]],
        strategy: CacheStrategy = CacheStrategy.AUTOMATIC_PREFIX,
    ) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None

        # Build stable cache key from canonical tool schemas (including types, parameters, descriptions)
        canonical = canonicalize_tool_schemas(tools)
        if not canonical:
            return None

        schema_blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        schema_hash = hashlib.sha256(schema_blob.encode("utf-8")).hexdigest()[:16]
        cache_key = f"{strategy.value}:{schema_hash}"

        with self._tool_cache_lock:
            if cache_key in self._tool_format_cache:
                self._tool_format_cache.move_to_end(cache_key)
                return self._tool_format_cache[cache_key]

        formatted = format_cached_tools(canonical, strategy=strategy)
        if formatted is not None:
            with self._tool_cache_lock:
                if len(self._tool_format_cache) >= self._max_tool_cache_size:
                    self._tool_format_cache.popitem(last=False)
                self._tool_format_cache[cache_key] = formatted

        return formatted

    def extract_cached_tokens(self, response_or_usage: Any) -> int:
        return extract_cached_tokens(response_or_usage)

    def record_usage(
        self,
        model: str,
        prompt_tokens: int,
        cached_tokens: int,
    ) -> None:
        self.metrics.record_turn(
            model=model,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
        )


# Global singleton access
get_cache_manager = UnifiedPromptCacheManager.get_instance
