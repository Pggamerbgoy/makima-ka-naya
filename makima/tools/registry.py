"""
Makima v2 — Dynamic Tool Registry & Auto-Discovery.
Architectural Pattern: Clean, lightweight Hermes-style tool registry with Pydantic v2 dynamic schema synthesis.
Zero-Hardcoding Guarantee: Fully dynamic schema auto-discovery, introspection, and safe execution sandboxing.
"""

from __future__ import annotations

import asyncio
import difflib
import importlib
import inspect
import json
import logging
import pkgutil
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    get_type_hints,
)

from pydantic import BaseModel, ConfigDict, Field, create_model

logger = logging.getLogger(__name__)

# Concurrency Classification Tag Boundaries
DEFAULT_PARALLEL_SAFE_TAGS: Set[str] = {
    "search", "read", "info", "system_info", "stats", "telemetry",
    "web", "internet", "research", "query", "memory", "filesystem_read",
}
DEFAULT_MUTATING_TAGS: Set[str] = {
    "desktop", "input", "write", "delete", "control", "exec", "terminal",
    "kill", "window", "mouse", "keyboard", "uia", "mutating",
}

# Canonical tool aliases for seamless resolution of consolidated tools
CANONICAL_TOOL_ALIASES: Dict[str, str] = {
    "search_web": "web_search",
    "fetch_web_page": "fetch_page",
    "launch_app": "launch_application",
    "remember_preference": "remember_user_preference",
    "save_preference": "remember_user_preference",
    "save_fact": "remember_fact",
    "kill_port": "free_port",
    "release_port": "free_port",
    "copy_to_clipboard": "set_clipboard_text",
    "read_clipboard": "get_clipboard_text",
    "whatsapp_send": "send_whatsapp_message",
    "send_whatsapp": "send_whatsapp_message",
    "whatsapp_status": "check_whatsapp_status",
}


def get_concurrency_tag_boundaries() -> Tuple[Set[str], Set[str]]:
    """
    Dynamically loads tag boundaries from MakimaSettings (configs/settings.yaml),
    falling back to standard defaults if settings are uninitialized or in test isolation.
    """
    try:
        from makima.config import get_settings
        settings = get_settings()
        if hasattr(settings, "tools") and hasattr(settings.tools, "concurrency"):
            cc = settings.tools.concurrency
            safe = {t.lower() for t in cc.parallel_safe_tags}
            mut = {t.lower() for t in cc.mutating_tags}
            return safe, mut
    except Exception:
        pass
    return set(DEFAULT_PARALLEL_SAFE_TAGS), set(DEFAULT_MUTATING_TAGS)


def infer_parallel_safe(
    tags: List[str],
    explicit: Optional[bool] = None,
    safe_tags: Optional[Set[str]] = None,
    mutating_tags: Optional[Set[str]] = None,
) -> bool:
    """Infers whether a tool can safely run concurrently with other read-only tools."""
    if explicit is not None:
        return bool(explicit)
    if safe_tags is None or mutating_tags is None:
        dyn_safe, dyn_mut = get_concurrency_tag_boundaries()
        safe_tags = safe_tags if safe_tags is not None else dyn_safe
        mutating_tags = mutating_tags if mutating_tags is not None else dyn_mut

    tag_set = {t.lower() for t in tags}
    if tag_set.intersection(mutating_tags):
        return False
    if tag_set.intersection(safe_tags):
        return True
    return False



# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """Base exception for all tool registry and execution errors."""
    pass


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found in the registry."""
    pass


class ToolValidationError(ToolError):
    """Raised when tool arguments fail validation against synthesized schema."""
    pass


class ToolExecutionError(ToolError):
    """Raised when a tool encounters an unhandled runtime error during execution."""
    pass


class CapabilityToolRegistry:
    """Read/execute view of a registry for untrusted remote callers."""

    PROFILE_TAGS = {
        "chat": {"terminal", "filesystem", "desktop", "input", "delete", "control", "execution"},
        "desktop": {"terminal", "filesystem", "delete"},
        "files": {"terminal", "desktop", "input", "delete"},
        "terminal": {"desktop", "input"},
        "full": set(),
    }

    def __init__(self, registry: "ToolRegistry", profile: str = "chat") -> None:
        self.registry = registry
        self.profile = profile if profile in self.PROFILE_TAGS else "chat"

    def _allowed(self, tool: "Tool") -> bool:
        blocked = self.PROFILE_TAGS[self.profile]
        return self.profile == "full" or not blocked.intersection(tool.tags)

    def list_tools(self, tags: Optional[List[str]] = None) -> List["Tool"]:
        tools = [tool for tool in self.registry.list_tools(tags=tags) if self._allowed(tool)]
        return tools

    def list_names(self, tags: Optional[List[str]] = None) -> List[str]:
        return [tool.name for tool in self.list_tools(tags=tags)]

    def get_schemas(self, format: str = "openai", tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        available_tools = self.list_tools(tags=tags)
        available_names = {tool.name for tool in available_tools}
        return [
            tool.to_schema(format=format)
            for tool in available_tools
            if not tool.fallback_for or tool.fallback_for not in available_names
        ]

    def get_all_schemas(self, format: str = "openai", tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Return all schemas allowed by this capability profile, including fallback tools."""
        return [tool.to_schema(format=format) for tool in self.list_tools(tags=tags)]

    async def execute(self, name: str, arguments: Optional[Dict[str, Any]] = None, catch_errors: bool = True) -> Any:
        tool = self.registry.get(name)
        if tool is None or not self._allowed(tool):
            message = f"Tool '{name}' is not permitted for capability profile '{self.profile}'."
            if not catch_errors:
                raise ToolError(message)
            return f"[TOOL_DENIED: {name}] {message}"
        return await self.registry.execute(name, arguments, catch_errors=catch_errors)

    def is_parallel_safe(self, name: str) -> bool:
        """Checks if a tool is permitted and safe for concurrent execution."""
        tool = self.registry.get(name)
        if tool is None or not self._allowed(tool):
            return False
        return bool(tool.parallel_safe)


# ---------------------------------------------------------------------------
# Docstring & Schema Introspection Helpers
# ---------------------------------------------------------------------------

def parse_docstring_params(doc: Optional[str]) -> Dict[str, str]:
    """
    Extracts parameter descriptions from Google, Sphinx, or reST style docstrings.
    """
    if not doc:
        return {}

    # Normalize nested/local tool docstrings before matching Args fields.
    # Extra source indentation otherwise prevents descriptions from reaching schemas.
    params: Dict[str, str] = {}
    lines = inspect.cleandoc(doc).splitlines()

    # 1. Sphinx / reST style: :param name: description
    sphinx_pattern = re.compile(r"^\s*:param\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$")
    for line in lines:
        m = sphinx_pattern.match(line)
        if m:
            params[m.group(1)] = m.group(2).strip()

    if params:
        return params

    # 2. Google / Numpy style:
    # Args:
    #     param_name (type): description
    #     param_name: description
    in_args_section = False
    current_param: Optional[str] = None
    param_pattern = re.compile(r"^\s{4,8}([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\([^)]*\))?\s*:\s*(.+)?$")

    for line in lines:
        stripped = line.strip()
        if stripped in ("Args:", "Arguments:", "Parameters:", "Parameters\n----------"):
            in_args_section = True
            continue
        elif in_args_section and stripped and not line.startswith(" ") and not line.startswith("\t"):
            in_args_section = False
            current_param = None

        if in_args_section:
            m = param_pattern.match(line)
            if m:
                current_param = m.group(1)
                desc = (m.group(2) or "").strip()
                params[current_param] = desc
            elif current_param and stripped and (line.startswith("        ") or line.startswith("\t\t")):
                params[current_param] += " " + stripped

    return params


def extract_docstring_description(doc: Optional[str]) -> str:
    """
    Extracts high-level tool description from docstring, stripping Args/Parameters blocks.
    """
    if not doc:
        return ""

    cleaned = inspect.cleandoc(doc)
    lines: List[str] = []
    for line in cleaned.splitlines():
        lower = line.strip().lower()
        if lower in ("args:", "arguments:", "parameters:", "returns:", "raises:") or lower.startswith(":param"):
            break
        lines.append(line)

    return "\n".join(lines).strip()


def synthesize_parameters_schema(
    fn: Callable,
) -> Tuple[Dict[str, Any], Optional[Type[BaseModel]], List[str], bool]:
    """
    Auto-synthesizes Pydantic v2 JSON schema and validation model from Python type annotations.
    Returns:
        (parameters_schema, args_model, positional_only_param_names, has_kwargs)
    """
    sig = inspect.signature(fn)
    try:
        type_hints = get_type_hints(fn)
    except Exception:
        type_hints = {}

    doc_params = parse_docstring_params(fn.__doc__)

    fields: Dict[str, Tuple[Any, Any]] = {}
    pos_only_names: List[str] = []
    has_kwargs = False

    for param_name, param in sig.parameters.items():
        # Skip self / cls
        if param_name in ("self", "cls"):
            continue

        # Check for varargs (*args, **kwargs)
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_kwargs = True
            continue

        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            pos_only_names.append(param_name)

        # Resolve type annotation
        annotation = type_hints.get(param_name, param.annotation)
        if annotation is inspect.Parameter.empty:
            annotation = Any

        # Check docstring description
        doc_desc = doc_params.get(param_name)

        # Determine default
        if param.default is inspect.Parameter.empty:
            # Required parameter
            if doc_desc:
                field_val = Field(..., description=doc_desc)
            else:
                field_val = ...
        else:
            # Optional parameter with default
            if doc_desc:
                field_val = Field(default=param.default, description=doc_desc)
            else:
                field_val = param.default

        fields[param_name] = (annotation, field_val)

    # Build dynamic Pydantic v2 model
    model_name = f"{getattr(fn, '__name__', 'anonymous')}_args"
    config = ConfigDict(extra="allow" if has_kwargs else "ignore", arbitrary_types_allowed=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        try:
            ArgsModel = create_model(model_name, __config__=config, **fields)
            raw_schema = ArgsModel.model_json_schema()
        except Exception:
            # Fallback: sanitize fields whose types cannot be converted to JSON Schema
            safe_fields: Dict[str, Tuple[Any, Any]] = {}
            for k, (ann, val) in fields.items():
                try:
                    test_m = create_model(f"test_{k}", __config__=config, **{k: (ann, val)})
                    test_m.model_json_schema()
                    safe_fields[k] = (ann, val)
                except Exception:
                    safe_fields[k] = (Any, val)
            ArgsModel = create_model(model_name, __config__=config, **safe_fields)
            raw_schema = ArgsModel.model_json_schema()

    # Clean schema for strict LLM API consumption (OpenAI & Groq standards)
    def _enforce_strict_schema(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        if obj.get("type") == "object":
            obj["additionalProperties"] = False
            p = obj.get("properties")
            if p and isinstance(p, dict):
                # Retain only actual required fields computed by Pydantic; do not force optional parameters to required
                if obj is clean_schema:
                    actual_req = raw_schema.get("required", [])
                    obj["required"] = [k for k in actual_req if k in p]
                elif "required" in obj:
                    obj["required"] = [k for k in obj["required"] if k in p]
                else:
                    obj.pop("required", None)
                for val in p.values():
                    _enforce_strict_schema(val)
            else:
                obj.pop("required", None)
        for k, v in obj.items():
            if isinstance(v, dict):
                _enforce_strict_schema(v)
            elif isinstance(v, list):
                for item in v:
                    _enforce_strict_schema(item)

    clean_schema: Dict[str, Any] = {
        "type": "object",
        "properties": raw_schema.get("properties", {}),
    }
    if "$defs" in raw_schema and raw_schema["$defs"]:
        clean_schema["$defs"] = raw_schema["$defs"]

    _enforce_strict_schema(clean_schema)

    return clean_schema, ArgsModel, pos_only_names, has_kwargs


# ---------------------------------------------------------------------------
# Tool Class
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    """Represents an executable tool registered in the Makima ecosystem."""
    name: str
    description: str
    fn: Callable
    tags: List[str] = field(default_factory=list)
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    args_model: Optional[Type[BaseModel]] = None
    positional_only_params: List[str] = field(default_factory=list)
    has_kwargs: bool = False
    is_async: bool = False
    parallel_safe: bool = False
    purpose: str = ""
    capabilities: List[str] = field(default_factory=list)
    use_when: List[str] = field(default_factory=list)
    avoid_when: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    side_effect: str = ""
    fallback_for: Optional[str] = None

    @property
    def selection_guidance(self) -> str:
        """Natural-language usage metadata consumed by schema and retrieval layers."""
        sections = []
        for label, values in (
            ("Purpose", [self.purpose] if self.purpose else []),
            ("Capabilities", self.capabilities),
            ("Use when", self.use_when),
            ("Do not use when", self.avoid_when),
            ("Examples", self.examples),
            ("Side effects", [self.side_effect] if self.side_effect else []),
        ):
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            if cleaned:
                sections.append(f"{label}: " + "; ".join(cleaned))
        return "\n".join(sections)

    @property
    def model_description(self) -> str:
        """Complete description shown to the LLM without changing the canonical base description."""
        guidance = self.selection_guidance
        if self.fallback_for:
            fallback_guidance = (
                f"Fallback tool for '{self.fallback_for}'. Use only when that primary tool is unavailable."
            )
            guidance = f"{guidance}\n{fallback_guidance}" if guidance else fallback_guidance
        if not guidance:
            return self.description
        return f"{self.description}\n\n{guidance}"

    @classmethod
    def from_function(
        cls,
        fn: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parallel_safe: Optional[bool] = None,
        safe_tags: Optional[Set[str]] = None,
        mutating_tags: Optional[Set[str]] = None,
        purpose: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        use_when: Optional[List[str]] = None,
        avoid_when: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        side_effect: Optional[str] = None,
        fallback_for: Optional[str] = None,
    ) -> "Tool":
        """Builds a Tool instance by introspecting a function."""
        tool_name = name or getattr(fn, "__name__", "unnamed_tool")
        tool_desc = (
            description
            or extract_docstring_description(fn.__doc__)
            or tool_name
        )
        tool_tags = list(tags) if tags else []

        parameters_schema, args_model, pos_only, has_kw = synthesize_parameters_schema(fn)
        is_coroutine = inspect.iscoroutinefunction(fn)
        safe = infer_parallel_safe(
            tool_tags,
            explicit=parallel_safe,
            safe_tags=safe_tags,
            mutating_tags=mutating_tags,
        )

        return cls(
            name=tool_name,
            description=tool_desc,
            fn=fn,
            tags=tool_tags,
            parameters_schema=parameters_schema,
            args_model=args_model,
            positional_only_params=pos_only,
            has_kwargs=has_kw,
            is_async=is_coroutine,
            parallel_safe=safe,
            purpose=purpose or "",
            capabilities=list(capabilities or []),
            use_when=list(use_when or []),
            avoid_when=list(avoid_when or []),
            examples=list(examples or []),
            side_effect=side_effect or "",
            fallback_for=fallback_for,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard OpenAI-compatible tool declaration."""
        fn_decl: Dict[str, Any] = {
            "name": self.name,
            "description": self.model_description,
            "parameters": self.parameters_schema,
        }
        if not self.has_kwargs:
            fn_decl["strict"] = True
        return {
            "type": "function",
            "function": fn_decl,
        }

    def to_gemini_dict(self) -> Dict[str, Any]:
        """Returns Gemini FunctionDeclaration-compatible dict."""
        return {
            "name": self.name,
            "description": self.model_description,
            "parameters": self.parameters_schema,
        }

    def to_schema(self, format: str = "openai") -> Dict[str, Any]:
        """Exports schema in requested LLM provider format ('openai' or 'gemini')."""
        if format.lower() == "gemini":
            return self.to_gemini_dict()
        return self.to_dict()


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Central registry for Makima tools.
    Provides dynamic schema auto-synthesis, auto-discovery, execution sandboxing,
    and [TOOL_FAILED: name] fallback generation with alternative hints.
    """

    def __init__(
        self,
        name: str = "default",
        safe_tags: Optional[Iterable[str]] = None,
        mutating_tags: Optional[Iterable[str]] = None,
    ):
        self.name = name
        self._tools: Dict[str, Tool] = {}
        self._discovered_tool_names: Set[str] = set()
        self._discovered = False
        self._discovering = False
        dyn_safe, dyn_mut = get_concurrency_tag_boundaries()
        self._safe_tags: Set[str] = {t.lower() for t in safe_tags} if safe_tags is not None else dyn_safe
        self._mutating_tags: Set[str] = {t.lower() for t in mutating_tags} if mutating_tags is not None else dyn_mut

    def configure_concurrency_tags(
        self,
        safe_tags: Optional[Iterable[str]] = None,
        mutating_tags: Optional[Iterable[str]] = None,
    ) -> None:
        """Dynamically reconfigures concurrency tag boundaries for this registry."""
        if safe_tags is not None:
            self._safe_tags = {t.lower() for t in safe_tags}
        if mutating_tags is not None:
            self._mutating_tags = {t.lower() for t in mutating_tags}

    def add_parallel_safe_tag(self, tag: str) -> None:
        """Dynamically registers a tag as safe for concurrent execution."""
        self._safe_tags.add(tag.lower())

    def add_mutating_tag(self, tag: str) -> None:
        """Dynamically registers a tag as mutating/sequential-only."""
        self._mutating_tags.add(tag.lower())

    def register_tool(self, tool: Tool) -> Tool:
        """Registers a pre-constructed Tool instance."""
        self._tools[tool.name] = tool
        return tool

    def register(
        self,
        tool_or_fn: Union[Tool, Callable],
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parallel_safe: Optional[bool] = None,
        purpose: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        use_when: Optional[List[str]] = None,
        avoid_when: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        side_effect: Optional[str] = None,
        fallback_for: Optional[str] = None,
    ) -> Tool:
        """
        Registers a function or Tool object into this registry.
        """
        if isinstance(tool_or_fn, Tool):
            return self.register_tool(tool_or_fn)

        if not callable(tool_or_fn):
            raise TypeError(f"Expected callable or Tool, got {type(tool_or_fn).__name__}")

        tool_obj = Tool.from_function(
            fn=tool_or_fn,
            name=name,
            description=description,
            tags=tags,
            parallel_safe=parallel_safe,
            safe_tags=self._safe_tags,
            mutating_tags=self._mutating_tags,
            purpose=purpose,
            capabilities=capabilities,
            use_when=use_when,
            avoid_when=avoid_when,
            examples=examples,
            side_effect=side_effect,
            fallback_for=fallback_for,
        )
        return self.register_tool(tool_obj)

    def unregister(self, name: str) -> Optional[Tool]:
        """Removes a tool from registry by name."""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """Retrieves a tool by name (exact match, case-insensitive, or canonical alias)."""
        if name in self._tools:
            return self._tools[name]
        lower_name = name.lower()
        for k, v in self._tools.items():
            if k.lower() == lower_name:
                return v
        # Resolve via canonical alias if not directly registered
        alias_target = CANONICAL_TOOL_ALIASES.get(name) or CANONICAL_TOOL_ALIASES.get(lower_name)
        if alias_target:
            return self.get(alias_target)
        return None

    def has(self, name: str) -> bool:
        """Checks if a tool name is registered."""
        return self.get(name) is not None

    def is_parallel_safe(self, name: str) -> bool:
        """Returns True if the registered tool is safe for concurrent execution."""
        tool = self.get(name)
        return bool(tool.parallel_safe) if tool else False

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __getitem__(self, name: str) -> Tool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found in registry '{self.name}'.")
        return tool

    def __iter__(self):
        return iter(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def clear(self) -> None:
        """Clears all registered tools."""
        self._tools.clear()
        self._discovered_tool_names.clear()
        self._discovered = False

    def list_tools(self, tags: Optional[List[str]] = None) -> List[Tool]:
        """Lists registered tools, optionally filtered by tags."""
        tools = list(self._tools.values())
        if not tags:
            return tools
        tag_set = set(tags)
        return [t for t in tools if any(tag in tag_set for tag in t.tags)]

    def list_names(self, tags: Optional[List[str]] = None) -> List[str]:
        """Lists names of registered tools, optionally filtered by tags."""
        return [t.name for t in self.list_tools(tags=tags)]

    def get_schemas(
        self,
        format: str = "openai",
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return primary tool schemas; conditional fallbacks are hidden while their primary is available."""
        tools = self.list_tools(tags=tags)
        active_names = {tool.name for tool in tools}
        return [
            tool.to_schema(format=format)
            for tool in tools
            if not tool.fallback_for or tool.fallback_for not in active_names
        ]

    def get_all_schemas(
        self,
        format: str = "openai",
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return all registered schemas, including conditional fallbacks, for explicit recovery turns."""
        return [tool.to_schema(format=format) for tool in self.list_tools(tags=tags)]

    def tool(
        self,
        name: Optional[Union[str, Callable]] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parallel_safe: Optional[bool] = None,
        purpose: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        use_when: Optional[List[str]] = None,
        avoid_when: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        side_effect: Optional[str] = None,
        fallback_for: Optional[str] = None,
    ) -> Callable:
        """Decorator to register a tool directly on this registry instance."""
        def decorator(fn: Callable) -> Callable:
            actual_name = name if isinstance(name, str) else fn.__name__
            actual_desc = description or extract_docstring_description(fn.__doc__)
            tool_obj = self.register(
                fn,
                name=actual_name,
                description=actual_desc,
                tags=tags,
                parallel_safe=parallel_safe,
                purpose=purpose,
                capabilities=capabilities,
                use_when=use_when,
                avoid_when=avoid_when,
                examples=examples,
                side_effect=side_effect,
                fallback_for=fallback_for,
            )
            setattr(fn, "__makima_tool__", True)
            setattr(fn, "__tool_name__", tool_obj.name)
            setattr(fn, "__tool_obj__", tool_obj)
            return fn

        if callable(name):
            fn = name
            name = None
            return decorator(fn)

        return decorator

    # -----------------------------------------------------------------------
    # Fallback Generator with Alternatives Hints
    # -----------------------------------------------------------------------

    def find_alternatives(
        self,
        name: str,
        tags: Optional[List[str]] = None,
        max_results: int = 3,
    ) -> List[str]:
        """
        Intelligently finds suggested alternative tools based on shared tags,
        token overlap, or string similarity.
        """
        candidates: List[str] = []
        target_tool = self._tools.get(name)
        query_tags = set(tags or (target_tool.tags if target_tool else []))

        # 1. Matching by shared tags
        if query_tags:
            for t_name, tool in self._tools.items():
                if t_name != name and set(tool.tags) & query_tags:
                    if t_name not in candidates:
                        candidates.append(t_name)

        # 2. Matching by token overlap (e.g. search_web vs search_local)
        name_tokens = set(re.split(r"[_\W]+", name.lower())) - {"", "get", "set", "do", "run"}
        if name_tokens:
            for t_name in self._tools.keys():
                if t_name != name and t_name not in candidates:
                    t_tokens = set(re.split(r"[_\W]+", t_name.lower()))
                    if name_tokens & t_tokens:
                        candidates.append(t_name)

        # 3. Matching by string similarity (difflib)
        other_tools = [k for k in self._tools.keys() if k != name and k not in candidates]
        close_matches = difflib.get_close_matches(name, other_tools, n=max_results, cutoff=0.4)
        for match in close_matches:
            if match not in candidates:
                candidates.append(match)

        # 4. Fallback if no specific matches found
        if not candidates:
            candidates = [k for k in self._tools.keys() if k != name][:max_results]

        return candidates[:max_results]

    def generate_fallback(
        self,
        name: str,
        error: Union[Exception, str],
        alternatives: Optional[List[str]] = None,
        hint: Optional[str] = None,
    ) -> str:
        """
        Generates structured [TOOL_FAILED: name] fallback message with error details
        and alternative suggestions for agent loops.
        """
        err_str = str(error)
        if isinstance(error, Exception):
            err_type = type(error).__name__
            err_text = f"{err_type}: {err_str}"
        else:
            err_text = err_str

        if alternatives is None:
            alts = self.find_alternatives(name)
        else:
            alts = alternatives

        lines = [f"[TOOL_FAILED: {name}] {err_text}"]
        if alts:
            lines.append(f"Suggested alternatives: {', '.join(alts)}")
        elif self._tools:
            available = list(self._tools.keys())[:3]
            lines.append(f"Available tools: {', '.join(available)}")
        else:
            lines.append("No alternative tools available in registry.")

        if hint:
            lines.append(f"Hint: {hint}")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Tool Execution
    # -----------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        catch_errors: bool = True,
    ) -> Any:
        """
        Executes a registered tool by name with arguments.
        Handles both sync (dispatched to thread pool) and async functions.
        Synthesizes/validates parameters through Pydantic v2.
        Returns result on success, or [TOOL_FAILED: name] fallback message on error.
        """
        tool = self.get(name)
        if tool is None:
            err = ToolNotFoundError(f"Tool '{name}' is not registered.")
            if not catch_errors:
                raise err
            return self.generate_fallback(name, err)

        # Handle raw json string arguments if passed from wire
        raw_args = arguments if arguments is not None else {}
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except Exception as parse_err:
                err = ToolValidationError(f"Invalid JSON string arguments: {parse_err}")
                if not catch_errors:
                    raise err
                return self.generate_fallback(name, err)

        if not isinstance(raw_args, dict):
            err = ToolValidationError(f"Tool arguments must be a dictionary, got {type(raw_args).__name__}")
            if not catch_errors:
                raise err
            return self.generate_fallback(name, err)

        # Validate arguments through synthesized Pydantic v2 model
        try:
            if tool.args_model is not None:
                validated = tool.args_model(**raw_args)
                kwargs = validated.model_dump()
            else:
                kwargs = dict(raw_args)
        except Exception as val_err:
            if not catch_errors:
                raise ToolValidationError(f"Invalid arguments for tool '{name}': {val_err}") from val_err
            return self.generate_fallback(
                name=name,
                error=val_err,
                hint="Verify argument types and required parameters against tool schema.",
            )

        # Map positional-only arguments if any exist
        pos_args = []
        if tool.positional_only_params:
            for p_name in tool.positional_only_params:
                if p_name in kwargs:
                    pos_args.append(kwargs.pop(p_name))

        # Execute tool (async directly, sync via asyncio.to_thread)
        try:
            if tool.is_async:
                result = await tool.fn(*pos_args, **kwargs)
            else:
                result = await asyncio.to_thread(tool.fn, *pos_args, **kwargs)
            return result
        except Exception as exec_err:
            logger.debug("Tool '%s' execution failed: %s", name, exec_err, exc_info=True)
            if not catch_errors:
                raise ToolExecutionError(
                    f"Tool '{name}' execution failed ({type(exec_err).__name__}): {exec_err}"
                ) from exec_err
            return self.generate_fallback(name=name, error=exec_err)

    # -----------------------------------------------------------------------
    # Auto-Discovery Scanner
    # -----------------------------------------------------------------------

    def _scan_module(self, mod: ModuleType, *, replace_existing: bool = False) -> int:
        """Register decorated tools; optionally replace stale implementations during reload."""
        count = 0
        for attr_name, attr_val in inspect.getmembers(mod):
            if callable(attr_val) and getattr(attr_val, "__makima_tool__", False):
                tool_obj = getattr(attr_val, "__tool_obj__", None)
                if tool_obj is None:
                    tool_obj = Tool.from_function(attr_val)
                self._discovered_tool_names.add(tool_obj.name)
                was_registered = tool_obj.name in self._tools
                if not was_registered or replace_existing:
                    self.register_tool(tool_obj)
                    if not was_registered:
                        count += 1
        return count

    def discover(
        self,
        package: Union[str, ModuleType, None] = "makima.tools",
        reload: bool = False,
    ) -> int:
        """
        Auto-discovers and registers tools in the given package and all submodules.
        Uses pkgutil.walk_packages and filesystem inspection to find @tool decorated functions.
        """
        if self._discovering:
            return 0
        self._discovering = True

        try:
            if reload:
                # Remove entries discovered during the previous scan before rescanning.
                # This clears renamed/deleted tools as well as replacing stale functions.
                for discovered_name in list(self._discovered_tool_names):
                    self.unregister(discovered_name)
                self._discovered_tool_names.clear()

            if self._discovered and not reload and package in (None, "makima.tools"):
                return 0

            target = package if package is not None else "makima.tools"
            pkg_name = target if isinstance(target, str) else getattr(target, "__name__", "")

            try:
                pkg = importlib.import_module(pkg_name) if isinstance(target, str) else target
                if reload and isinstance(target, str):
                    pkg = importlib.reload(pkg)
            except Exception as exc:
                logger.warning("Failed to import package '%s' for tool discovery: %s", pkg_name, exc)
                return 0

            discovered_count = 0

            # Scan the root module itself. An explicit reload must also refresh
            # already-registered Tool objects, not merely import fresh Python code.
            discovered_count += self._scan_module(pkg, replace_existing=reload)

            # If it's a package with __path__, traverse subpackages/submodules
            if hasattr(pkg, "__path__"):
                prefix = f"{pkg.__name__}."
                # 1. Standard pkgutil package walk
                for module_info in pkgutil.walk_packages(pkg.__path__, prefix=prefix):
                    if module_info.name.endswith(".registry") or module_info.name == __name__:
                        continue
                    try:
                        mod = importlib.import_module(module_info.name)
                        if reload:
                            mod = importlib.reload(mod)
                        discovered_count += self._scan_module(mod, replace_existing=reload)
                    except Exception as exc:
                        logger.warning("Error importing tool module '%s': %s", module_info.name, exc)

                # 2. Filesystem traversal for directories without __init__.py
                for p in pkg.__path__:
                    path_obj = Path(p)
                    if not path_obj.exists():
                        continue
                    for py_file in path_obj.rglob("*.py"):
                        if py_file.name.startswith("__") or py_file.stem == "registry":
                            continue
                        rel_parts = py_file.relative_to(path_obj).with_suffix("").parts
                        mod_name = f"{pkg.__name__}." + ".".join(rel_parts)
                        if mod_name not in sys.modules:
                            try:
                                mod = importlib.import_module(mod_name)
                                discovered_count += self._scan_module(mod, replace_existing=reload)
                            except Exception as exc:
                                logger.warning("Error importing tool file '%s': %s", py_file, exc)

            # The built-in catalogue and third-party plugin packages have separate
            # discovery lifecycles. Scanning one custom plugin must not prevent the
            # default makima.tools catalogue from being scanned later.
            if pkg_name == "makima.tools":
                self._discovered = True
            return discovered_count
        finally:
            self._discovering = False


# ---------------------------------------------------------------------------
# Global Registry & Module-Level @tool Decorator
# ---------------------------------------------------------------------------

_GLOBAL_REGISTRY: Optional[ToolRegistry] = None


def get_registry(auto_discover: bool = False) -> ToolRegistry:
    """Returns the singleton ToolRegistry instance."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ToolRegistry(name="global")
    if auto_discover and not _GLOBAL_REGISTRY._discovered:
        _GLOBAL_REGISTRY.discover()
    return _GLOBAL_REGISTRY


def reset_registry() -> None:
    """Resets the singleton ToolRegistry (for test isolation)."""
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = None


def tool(
    name: Optional[Union[str, Callable]] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    parallel_safe: Optional[bool] = None,
    purpose: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    use_when: Optional[List[str]] = None,
    avoid_when: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    side_effect: Optional[str] = None,
    fallback_for: Optional[str] = None,
) -> Callable:
    """
    Primary @tool decorator.
    Usage:
        @tool
        def my_func(a: int) -> int: ...

        @tool(name="custom_name", description="...", tags=["math"], parallel_safe=True)
        async def my_func(a: int) -> int: ...
    """
    def decorator(fn: Callable) -> Callable:
        actual_name = name if isinstance(name, str) else getattr(fn, "__name__", "unnamed_tool")
        actual_desc = description or extract_docstring_description(fn.__doc__)
        actual_tags = list(tags) if tags else []

        tool_obj = Tool.from_function(
            fn=fn,
            name=actual_name,
            description=actual_desc,
            tags=actual_tags,
            parallel_safe=parallel_safe,
            purpose=purpose,
            capabilities=capabilities,
            use_when=use_when,
            avoid_when=avoid_when,
            examples=examples,
            side_effect=side_effect,
            fallback_for=fallback_for,
        )

        setattr(fn, "__makima_tool__", True)
        setattr(fn, "__tool_name__", actual_name)
        setattr(fn, "__tool_description__", actual_desc)
        setattr(fn, "__tool_tags__", actual_tags)
        setattr(fn, "__tool_obj__", tool_obj)

        # Auto-register with global registry
        get_registry().register_tool(tool_obj)

        return fn

    if callable(name):
        fn = name
        name = None
        return decorator(fn)

    return decorator
