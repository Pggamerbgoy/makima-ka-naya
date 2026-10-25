"""Shared semantic tool selection and execution policy.

Tool availability is derived from the live registry and tool descriptions, not
from request-specific keyword maps. The LLM remains responsible for choosing an
actual action from the candidate schemas it receives.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from makima.core.guardrails import DangerousCommandError, Guardrails

logger = logging.getLogger(__name__)

TOOL_SELECTION_GUIDANCE = """
<tool_selection_policy>
- Interpret the latest request in the context of the conversation, preserving corrections, negation, and explicit constraints about what must remain unchanged.
- Choose actions by their intended outcome and the complete tool descriptions, capabilities, and argument schemas; do not rely on tool names or isolated words alone.
- Keep different targets and side effects distinct. For example, changing a media session, closing an application, closing a browser tab, and ending the assistant's voice session are different operations.
- For requests with multiple actions, complete each requested action while preserving every explicit constraint.
- Treat tool results as evidence. Inspect success fields and returned state before claiming an operation succeeded; never contradict a result that says the target was not found or an operation failed.
- Use only structured tool calls provided by the current tool interface. Do not invent tool-call traces or claim an action ran when it did not.
</tool_selection_policy>
""".strip()


def _function_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    fn = schema.get("function")
    return fn if isinstance(fn, dict) else schema


def _schema_name(schema: Dict[str, Any]) -> str:
    return str(_function_schema(schema).get("name") or "")


def _schema_text(schema: Dict[str, Any], tool_metadata: Optional[Dict[str, Any]] = None) -> str:
    fn = _function_schema(schema)
    name = str(fn.get("name") or "")
    description = str(fn.get("description") or "")
    parameters = fn.get("parameters") or {}
    metadata = (tool_metadata or {}).get(name)
    tags = getattr(metadata, "tags", ()) if metadata is not None else ()
    implementation_doc = getattr(getattr(metadata, "fn", None), "__doc__", None) if metadata is not None else None
    pieces = [
        f"Tool name: {name}",
        f"Purpose and behavior: {description}",
        f"Capabilities and tags: {'; '.join(str(tag) for tag in tags)}",
        f"Argument schema and argument meanings: {json.dumps(parameters, ensure_ascii=False, sort_keys=True)}",
    ]
    if implementation_doc:
        pieces.append(f"Additional implementation documentation: {implementation_doc.strip()[:1600]}")
    return "\n".join(piece for piece in pieces if piece)


class ToolSelectionService:
    """Retrieves a high-recall semantic candidate set for the LLM.

    The embedding index is rebuilt automatically whenever registered tool schemas
    change. If local embeddings are unavailable or relevance is uncertain, the
    service fails open and returns the complete available schema set rather than
    hiding a tool the model may need.
    """

    def __init__(
        self,
        config: Any = None,
        *,
        embedding_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.config = config or self._load_config()
        self.embedding_factory = embedding_factory
        self._embedder: Any = None
        self._lock = threading.RLock()
        self._catalog_signature: Optional[str] = None
        self._catalog_vectors: List[List[float]] = []
        self._catalog_texts: List[str] = []

    @staticmethod
    def _load_config() -> Any:
        from makima.config import ToolSelectionConfig, get_settings

        try:
            return get_settings().tools.selection
        except Exception as exc:
            logger.warning("Could not load tool-selection settings; using the configured model defaults: %s", exc)
            return ToolSelectionConfig()

    @classmethod
    def from_settings(cls) -> "ToolSelectionService":
        return cls()

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            if self.embedding_factory is not None:
                self._embedder = self.embedding_factory(str(self.config.embedding_model))
            else:
                from fastembed import TextEmbedding

                self._embedder = TextEmbedding(model_name=str(self.config.embedding_model))
        return self._embedder

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right or len(left) != len(right):
            return -1.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _vector_list(values: Iterable[Any]) -> List[List[float]]:
        return [[float(component) for component in vector] for vector in values]

    def _get_catalog_vectors(self, texts: List[str]) -> List[List[float]]:
        signature = hashlib.sha256(
            json.dumps(texts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if signature != self._catalog_signature:
            vectors = self._vector_list(self._get_embedder().embed(texts))
            self._catalog_texts = list(texts)
            self._catalog_vectors = vectors
            self._catalog_signature = signature
        return self._catalog_vectors

    def _select_sync(
        self,
        schemas: List[Dict[str, Any]],
        query: str,
        tool_metadata: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        with self._lock:
            texts = [_schema_text(schema, tool_metadata) for schema in schemas]
            embedder = self._get_embedder()
            catalog_vectors = self._get_catalog_vectors(texts)
            query_vector = self._vector_list(
                embedder.embed([f"User request and current task context: {query}"])
            )[0]
            scores = [self._cosine(query_vector, vector) for vector in catalog_vectors]

            minimum_similarity = float(getattr(self.config, "minimum_similarity", 0.20))
            minimum_candidates = max(1, int(getattr(self.config, "minimum_candidates", 16)))
            maximum_candidates = max(minimum_candidates, int(getattr(self.config, "max_candidates", 32)))

            ranked_indices = sorted(range(len(schemas)), key=lambda index: scores[index], reverse=True)
            if not ranked_indices or scores[ranked_indices[0]] < minimum_similarity:
                logger.info(
                    "Tool selection confidence is low; keeping all %d registered schemas available.",
                    len(schemas),
                )
                return schemas

            relevant = [index for index in ranked_indices if scores[index] >= minimum_similarity]
            if len(relevant) < minimum_candidates:
                relevant = ranked_indices[:minimum_candidates]
            selected_indices = ranked_indices[:maximum_candidates] if len(relevant) > maximum_candidates else relevant

            # Keep provider schema ordering stable for predictable request payloads and caching.
            chosen = set(selected_indices)
            return [schema for index, schema in enumerate(schemas) if index in chosen]

    async def select_schemas(
        self,
        schemas: Optional[List[Dict[str, Any]]],
        query: str,
        *,
        tool_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        if not schemas:
            return schemas
        enabled = bool(getattr(self.config, "enabled", True))
        maximum_candidates = max(1, int(getattr(self.config, "max_candidates", 32)))
        if not enabled or len(schemas) <= maximum_candidates or not query.strip():
            return schemas

        try:
            selected = await asyncio.to_thread(
                self._select_sync,
                list(schemas),
                query.strip(),
                tool_metadata,
            )
            logger.info(
                "Semantic tool retrieval selected %d of %d schemas for the current request.",
                len(selected),
                len(schemas),
            )
            return selected
        except Exception as exc:
            logger.warning(
                "Semantic tool retrieval is unavailable (%s); exposing all %d available schemas.",
                exc,
                len(schemas),
            )
            return schemas


class ToolExecutionGateway:
    """Common registry view that applies enabled-state and per-turn allowlists."""

    def __init__(
        self,
        registry: Any,
        disabled_tools: Optional[Callable[[], Iterable[str]] | Iterable[str]] = None,
        guardrails: Optional[Guardrails] = None,
    ) -> None:
        self.registry = registry
        self._disabled_tools = disabled_tools
        self.guardrails = guardrails or Guardrails()

    def _disabled_names(self) -> Set[str]:
        value = self._disabled_tools() if callable(self._disabled_tools) else self._disabled_tools
        return {str(name) for name in (value or ())}

    def is_enabled(self, name: str) -> bool:
        return name not in self._disabled_names()

    def list_tools(self, tags: Optional[List[str]] = None) -> List[Any]:
        return [
            tool for tool in self.registry.list_tools(tags=tags)
            if self.is_enabled(str(getattr(tool, "name", "")))
        ]

    def list_names(self, tags: Optional[List[str]] = None) -> List[str]:
        return [str(tool.name) for tool in self.list_tools(tags=tags)]

    def get_schemas(
        self,
        format: str = "openai",
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return [tool.to_schema(format=format) for tool in self.list_tools(tags=tags)]

    def is_parallel_safe(self, name: str) -> bool:
        if not self.is_enabled(name):
            return False
        if hasattr(self.registry, "is_parallel_safe"):
            return bool(self.registry.is_parallel_safe(name))
        return False

    async def execute(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        allowed_tool_names: Optional[Iterable[str]] = None,
    ) -> Any:
        if allowed_tool_names is not None and name not in set(allowed_tool_names):
            return f"[TOOL_NOT_AVAILABLE: {name}] This tool was not exposed for the current turn."
        if not self.is_enabled(name):
            return f"[TOOL_DISABLED: {name}] Tool disabled in Makima settings."
        if name not in set(self.registry.list_names()):
            return f"[TOOL_NOT_FOUND: {name}] Tool is not registered."
        try:
            self.guardrails.validate_tool_call(name, arguments or {})
        except DangerousCommandError as exc:
            logger.warning("Shared execution gateway blocked tool '%s': %s", name, exc)
            return f"[GUARDRAIL_BLOCKED: {name}] {exc}"
        return await self.registry.execute(name, arguments or {})
