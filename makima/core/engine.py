"""
Makima v2 — Hermes Core Agent Engine.
Architectural Pattern: Autonomous Hermes While-Loop with Pareto Fallback Routing, 
Dynamic Middle-Turn Context Compression, Dual-Layer Guardrail Interception,
and Dual-Tier Memory Integration (EpisodicMemory + VectorSearch + StateMemory).
Zero-Hardcoding Guarantee: Fully decoupled from model vendors, tool registries, and static prompt budgets.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field

from makima.core.context import ContextCompressor
from makima.core.guardrails import DangerousCommandError, Guardrails
from makima.core.prompts import DEFAULT_HERMES_SYSTEM_PROMPT
from makima.provider.adapters.base import Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter
from makima.tools.selection import ToolSelectionService

# Memory subsystems — optional, graceful degradation if not injected
try:
    from makima.memory.episodic import EpisodicMemory
    from makima.memory.state import StateMemory
    from makima.memory.vector_search import VectorSearchEngine
    from makima.memory.reflection import ImplicitPreferenceLearner
except ImportError:
    EpisodicMemory = None  # type: ignore
    StateMemory = None  # type: ignore
    VectorSearchEngine = None  # type: ignore
    ImplicitPreferenceLearner = None  # type: ignore

# Telemetry & Skills subsystems — optional, graceful fallback
try:
    from makima.core.telemetry import StructuredTelemetry, get_telemetry
except ImportError:
    StructuredTelemetry = None  # type: ignore
    get_telemetry = None  # type: ignore

try:
    from makima.skills.loader import SkillsLoader
except ImportError:
    SkillsLoader = None  # type: ignore

logger = logging.getLogger("makima.core.engine")


class EngineResult(BaseModel):
    """Encapsulates the final outcome of an autonomous agent execution run."""
    content: str
    messages: List[Message]
    turn_count: int
    tool_calls_executed: int
    completed: bool
    finish_reason: str = "stop"
    model_used: str = ""
    latency_ms: float = 0.0
    cached_tokens: int = 0
    error: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)


class HermesAgentEngine:
    """
    Autonomous Hermes agent while-loop execution engine.
    Orchestrates:
      1. User prompt ingestion and message history formatting.
      2. StateMemory + VectorSearch memory context injection into system prompt.
      3. Dynamic context compression when token budget is exceeded.
      4. ParetoRouter cascade dispatch with automatic circuit breaker fallback.
      5. Structured tool call parsing, guardrail verification, and dispatch.
      6. Recursive result collation until final answer or max_turns guard reached.
      7. EpisodicMemory persistence of all turns post-run (background task).
    """

    DEFAULT_SYSTEM_PROMPT: str = DEFAULT_HERMES_SYSTEM_PROMPT

    @staticmethod
    def _extract_suggestions(text: str) -> tuple[str, list[str]]:
        """Extracts JSON suggestions block from model response and returns clean text and suggestions list."""
        if not text:
            return "", []
        pattern = r"```(?:suggestions|json)?\s*(\[[\s\S]*?\])\s*```"
        match = re.search(pattern, text)
        if not match:
            return text.strip(), []
        try:
            parsed = json.loads(match.group(1))
            suggestions = [str(s).strip() for s in parsed if s][:3] if isinstance(parsed, list) else []
            clean = (text[:match.start()] + text[match.end():]).strip()
            return clean, suggestions
        except Exception:
            return text.strip(), []

    def __init__(
        self,
        router: Optional[ParetoRouter] = None,
        compressor: Optional[ContextCompressor] = None,
        guardrails: Optional[Guardrails] = None,
        default_task: str = "fast_chat",
        max_turns: int = 30,
        # Memory subsystems — all optional, engine degrades gracefully without them
        episodic_memory: Optional[Any] = None,
        vector_search: Optional[Any] = None,
        state_memory: Optional[Any] = None,
        memory_top_k: int = 5,
        preference_learner: Optional[Any] = None,
        enable_implicit_learning: bool = True,
        # Skills & Telemetry subsystems — optional
        skills_loader: Optional[Any] = None,
        telemetry: Optional[Any] = None,
        tool_selector: Optional[Any] = None,
    ):
        self.router = router or ParetoRouter()
        self.compressor = compressor or ContextCompressor()
        self.guardrails = guardrails or Guardrails()
        self.default_task = default_task
        self.max_turns = max_turns

        # Memory subsystems
        self.episodic_memory = episodic_memory
        self.vector_search = vector_search
        self.state_memory = state_memory
        self.memory_top_k = memory_top_k
        self.enable_implicit_learning = enable_implicit_learning

        if preference_learner is not None:
            self.preference_learner = preference_learner
        elif enable_implicit_learning and self.state_memory is not None and ImplicitPreferenceLearner is not None:
            self.preference_learner = ImplicitPreferenceLearner(
                state_memory=self.state_memory,
                router=self.router,
            )
        else:
            self.preference_learner = None

        # Skills & Telemetry subsystems
        self.skills_loader = skills_loader
        self.telemetry = telemetry if telemetry is not None else (get_telemetry() if get_telemetry else None)
        self.tool_selector = tool_selector or ToolSelectionService.from_settings()

        # Background task registry — strong references prevent GC mid-execution
        self._background_tasks: Set[asyncio.Task] = set()

    @property
    def episodic(self) -> Optional[Any]:
        return self.episodic_memory

    @property
    def state(self) -> Optional[Any]:
        return self.state_memory

    @property
    def vector(self) -> Optional[Any]:
        return self.vector_search

    @staticmethod
    def _tool_selection_context(prompt: Optional[str], messages: List[Message]) -> str:
        """Build current-request-first retrieval context for bounded embedding models."""
        current_request = (prompt or "").strip()
        if not current_request:
            current_request = next(
                ((message.content or "").strip() for message in reversed(messages) if message.role == "user" and (message.content or "").strip()),
                "",
            )

        parts: List[str] = []
        if current_request:
            parts.append(f"Current user request: {current_request[:700]}")

        # Recent actions and outcomes follow the current request, not precede it.
        # This makes the latest correction more likely to survive embedding token limits.
        seen_current = False
        recent = list(reversed(messages[-12:]))
        for message in recent:
            role = message.role
            if role not in {"user", "assistant", "tool"}:
                continue

            content = (message.content or "").strip()
            if role == "user" and content:
                if not seen_current and current_request and content == current_request:
                    seen_current = True
                    continue
                parts.append(f"Recent user context: {content[:260]}")
            elif role == "assistant":
                if content:
                    parts.append(f"Recent assistant response: {content[:220]}")
                for call in getattr(message, "tool_calls", None) or []:
                    call_name = getattr(call, "name", "") or ""
                    call_arguments = getattr(call, "arguments", {}) or {}
                    if call_name:
                        parts.append(
                            "Recent structured action: "
                            + json.dumps(
                                {"tool": call_name, "arguments": call_arguments},
                                ensure_ascii=False,
                                default=str,
                            )[:320]
                        )
            elif role == "tool" and content:
                tool_name = getattr(message, "name", None) or "tool"
                parts.append(f"Recent observed result ({tool_name}): {content[:320]}")

            if sum(len(part) for part in parts) >= 2400:
                break

        context = "\n".join(parts)
        return context[:3000]

    def _resolve_model_and_context_limit(
        self,
        active_task: str = "general",
        preferred_backend: Optional[str] = None,
    ) -> Tuple[str, int]:
        """
        Resolves the target model identifier and effective context window token limit.
        Checks:
          1. Candidate Provider's BackendConfig.context_limit (user setting from YAML).
          2. Known model name patterns via ContextCompressor.get_model_context_limit().
          3. ContextCompressor.max_tokens default (286,000 tokens).
        """
        model_name = preferred_backend or ""
        configured_limit: Optional[int] = None

        if self.router is not None:
            try:
                candidates = self.router.get_ranked_candidates(active_task)
                if preferred_backend:
                    matched = [c for c in candidates if c.name == preferred_backend]
                    candidate = matched[0] if matched else (candidates[0] if candidates else None)
                else:
                    candidate = candidates[0] if candidates else None

                if candidate and hasattr(candidate, "provider"):
                    p_cfg = getattr(candidate.provider, "config", None)
                    if p_cfg:
                        model_name = getattr(p_cfg, "model", None) or model_name
                        raw_lim = getattr(p_cfg, "context_limit", None)
                        if raw_lim and isinstance(raw_lim, int) and raw_lim > 0:
                            configured_limit = raw_lim
            except Exception as exc:
                logger.debug("Router candidate resolution in _resolve_model_and_context_limit: %s", exc)

        if configured_limit is None:
            configured_limit = ContextCompressor.get_model_context_limit(model_name)

        if configured_limit is None:
            configured_limit = getattr(self.compressor, "max_tokens", 286_000)

        return model_name, configured_limit

    def _calculate_history_token_budget(
        self,
        system_prompt: Optional[str] = None,
        current_prompt: Optional[str] = None,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        active_task: str = "general",
        preferred_backend: Optional[str] = None,
        max_output_tokens: int = 4096,
        max_allowed_history: Optional[int] = None,
    ) -> int:
        """
        Computes the history budget from the selected model's real context limit.

        The budget reserves space for the system prompt, current user prompt, tools,
        completion, and safety headroom. By default there is no arbitrary history
        ceiling: the remaining context is available for history. Callers may supply
        max_allowed_history as an explicit operational cap.
        """
        _, context_limit = self._resolve_model_and_context_limit(active_task, preferred_backend)

        counter = getattr(self.compressor, "counter", None)
        count_text = getattr(counter, "count_text", None)
        effective_sys = system_prompt if system_prompt is not None else getattr(self, "DEFAULT_SYSTEM_PROMPT", "")
        sys_tokens = count_text(effective_sys) if callable(count_text) else (len(effective_sys) // 4)
        prompt_tokens = (
            count_text(current_prompt) if callable(count_text) else (len(current_prompt) // 4)
        ) if current_prompt else 0

        tool_tokens = 0
        if tool_schemas:
            try:
                serialized_schemas = json.dumps(
                    tool_schemas,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=str,
                )
                tool_tokens = count_text(serialized_schemas) if callable(count_text) else (len(serialized_schemas) // 4)
            except Exception:
                tool_tokens = len(tool_schemas) * 120

        reserved_output = max(0, int(max_output_tokens))
        headroom = max(2048, int(context_limit * 0.10))
        available = max(
            0,
            context_limit - (sys_tokens + prompt_tokens + tool_tokens + reserved_output + headroom),
        )
        if max_allowed_history is not None:
            available = min(available, max(0, int(max_allowed_history)))
        return available

    @classmethod
    def _strip_spoofed_tool_traces(cls, text: str) -> str:
        """Strips faked '[Executed Tools in Turn: ...]' mock logs from assistant text response."""
        if not text:
            return ""
        return re.sub(r"\[Executed Tools in Turn:.*?\]", "", text, flags=re.DOTALL).strip()

    async def _execute_tool_call(
        self,
        call: ToolCall,
        tool_executor: Optional[Callable[..., Any]],
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> str:
        """
        Validates safety guardrails and dispatches an individual tool call.
        Implements resilient error formatting to allow agent self-correction.
        """
        # A structured call may execute only when its schema was exposed this turn.
        actual_name = call.name.split(":")[-1] if ":" in call.name else call.name
        if allowed_tool_names is not None:
            if call.name not in allowed_tool_names and actual_name in allowed_tool_names:
                call.name = actual_name
            elif call.name not in allowed_tool_names:
                logger.warning("Rejected tool call not present in the active schema set: %s", call.name)
                return f"[TOOL_NOT_AVAILABLE: {call.name}] The tool was not exposed for this turn; choose an available tool."

        # 1. Guardrail safety check (e.g. dangerous terminal / SQL commands)
        try:
            self.guardrails.validate_tool_call(call.name, call.arguments)
        except DangerousCommandError as dce:
            logger.warning(f"Guardrail intercepted dangerous tool execution for '{call.name}': {dce}")
            return f"[GUARDRAIL_BLOCKED: {call.name}] {dce}"

        # 2. Verify tool executor availability
        if tool_executor is None:
            return f"[TOOL_FAILED: {call.name}] No tool executor available to handle this tool."

        # 3. Execute tool call safely with timeout protection
        t0 = time.monotonic()
        timeout_s = getattr(self, "tool_timeout", None)
        if timeout_s is None:
            try:
                from makima.config import get_settings
                timeout_s = float(get_settings().tool_timeout or 45.0)
            except Exception:
                timeout_s = 45.0

        try:
            async def _run_tool():
                if inspect.iscoroutinefunction(tool_executor):
                    return await tool_executor(call.name, call.arguments)
                else:
                    res = tool_executor(call.name, call.arguments)
                    if inspect.isawaitable(res):
                        return await res
                    return res

            raw_result = await asyncio.wait_for(_run_tool(), timeout=timeout_s)

            # Format tool result
            if isinstance(raw_result, (dict, list)):
                result_str = json.dumps(raw_result, ensure_ascii=False)
            else:
                result_str = str(raw_result)

            lat_ms = (time.monotonic() - t0) * 1000.0
            if self.telemetry:
                self.telemetry.emit_sync("tool.execute", {"tool": call.name, "latency_ms": round(lat_ms, 2)})

        except Exception as e:
            lat_ms = (time.monotonic() - t0) * 1000.0
            logger.error(f"Error executing tool '{call.name}': {e}", exc_info=True)
            if self.telemetry:
                self.telemetry.emit_sync("tool.error", {"tool": call.name, "error": str(e), "latency_ms": round(lat_ms, 2)})
            # Self-healing signal conforming to Master Plan spec: [TOOL_FAILED: name]
            result_str = f"[TOOL_FAILED: {call.name}] {type(e).__name__}: {str(e)}"

        # 4. Cap oversized tool output dynamically with head/tail preservation (F1.3)
        max_tool_chars = 16000
        try:
            from makima.config import get_settings
            max_tool_chars = int(get_settings().max_tool_output_chars or 16000)
        except Exception:
            pass

        head_chars = int(max_tool_chars * 0.68)
        tail_chars = max_tool_chars - head_chars
        if len(result_str) > max_tool_chars:
            omitted = len(result_str) - (head_chars + tail_chars)
            result_str = (
                f"{result_str[:head_chars]}\n"
                f"[... truncated {omitted} characters ...]\n"
                f"{result_str[-tail_chars:]}"
            )

        # 5. Redact potential secret leaks from tool output before feeding back to model
        return self.guardrails.filter_secrets(result_str)

    def _sanitize_degenerate_post_tool_greeting(
        self,
        content: str,
        working_messages: List[Message],
        total_tool_calls: int,
    ) -> str:
        """
        Intercepts hallucinated/degenerate conversational resets (e.g. 'Hello, pg. Kya kaam hai aaj?')
        that some models emit after finishing concrete tool actions, replacing it with an accurate
        factual summary of what actions were performed.
        """
        if total_tool_calls <= 0 or not content:
            return content

        norm = content.strip().lower()
        prefixes = (
            "hello", "hi there", "hey there", "hi pg", "hello pg", "kya kaam", "aaj kya", "namaste",
            "how can i help", "how may i help", "what can i do", "boliye", "bolo", "haan pg"
        )
        is_greeting = (
            any(norm.startswith(prefix) for prefix in prefixes)
            and (
                (len(norm) < 140 and any(kw in norm for kw in ("kaam", "help", "assist", "today", "aaj", "karein", "bataiye", "batao")))
                or len(norm) < 40
            )
        )

        if not is_greeting:
            return content

        tools_executed = [
            f"{m.name}" for m in working_messages if m.role == "tool" and m.name
        ]
        last_tool_msg = next((m.content for m in reversed(working_messages) if m.role == "tool"), "")
        summary_str = ", ".join(tools_executed[-4:]) if tools_executed else "desktop actions"

        detail_msg = ""
        if last_tool_msg:
            try:
                parsed = json.loads(last_tool_msg)
                if isinstance(parsed, dict):
                    if "active_window" in parsed:
                        detail_msg = f" Target window: {parsed['active_window']}."
                    elif "track" in parsed or "title" in parsed:
                        detail_msg = f" Current track: {parsed.get('title') or parsed.get('track')}."
                    elif "text" in parsed:
                        detail_msg = f" Extracted text: {str(parsed['text'])[:120]}..."
                    elif "url" in parsed:
                        detail_msg = f" Page: {parsed.get('url')}."
                    elif "status" in parsed:
                        detail_msg = f" Status: {parsed.get('status')}."
            except Exception:
                detail_msg = f" Result: {last_tool_msg[:160]}..."

        return f"Executed desktop actions ({summary_str}) successfully.{detail_msg}"

    async def _build_memory_context(self, prompt: str, session_id: Optional[str]) -> str:
        """
        Builds a memory context block to prepend to the system prompt.
        Pulls from StateMemory (user facts) and VectorSearchEngine (semantic recall).
        Conversation turns are hydrated directly into working_messages to prevent prompt duplication.
        Returns empty string if session_id is not set or no memory subsystems are configured.
        """
        if not session_id:
            return ""

        parts: List[str] = []

        # 1. StateMemory — inject MEMORY.md and USER.md facts
        if self.state_memory is not None:
            try:
                facts = await asyncio.to_thread(self.state_memory.format_prompt_injection)
                if facts and facts.strip():
                    parts.append(facts.strip())
            except Exception as e:
                logger.debug(f"StateMemory injection skipped: {e}")

        # 2. VectorSearch — semantic recall of relevant past turns
        if self.vector_search is not None and prompt:
            try:
                hits = await self.vector_search.search(prompt)
                if hits:
                    recall_lines = []
                    for h in hits:
                        text = h.get("content") or h.get("text") or ""
                        doc_id = h.get("doc_id", "doc")
                        dist = h.get("distance")
                        if dist is not None:
                            recall_lines.append(f"- [{doc_id}] {text[:200]} (distance={dist:.2f})")
                        else:
                            recall_lines.append(f"- [{doc_id}] {text[:200]}")
                    if recall_lines:
                        parts.append("## Relevant Memory\n" + "\n".join(recall_lines))
            except Exception as e:
                logger.debug(f"VectorSearch recall skipped: {e}")

        if not parts:
            return ""

        inner = "\n\n".join(parts)
        return f"<memory>\n{inner}\n</memory>"

    async def _build_skills_context(self, prompt: str) -> str:
        """
        Builds a skills markdown section matching user prompt keywords or active skills.
        """
        if self.skills_loader is None or not prompt:
            return ""
        try:
            matching = await asyncio.to_thread(self.skills_loader.search_skills, prompt)
            if not matching:
                # If full prompt sentence didn't match, check individual meaningful keywords
                matching = []
                words = [w.strip() for w in re.findall(r"\b\w+\b", prompt.lower()) if len(w.strip()) > 3]
                stop_words = {"what", "when", "where", "which", "with", "from", "that", "this", "then", "have", "make", "does", "right", "know", "please"}
                keywords = [w for w in words if w not in stop_words]
                for kw in keywords:
                    kw_matches = await asyncio.to_thread(self.skills_loader.search_skills, kw)
                    if kw_matches:
                        for m in kw_matches:
                            if m not in matching:
                                matching.append(m)
            # F1.1: Only inject skills that genuinely match the prompt; avoid injecting arbitrary fallback skills
            if matching:
                raw_skills = await asyncio.to_thread(
                    self.skills_loader.build_system_prompt_section, matching, 1000
                )
                if raw_skills:
                    return f"<skills>\n{raw_skills}\n</skills>"
        except Exception as e:
            logger.debug(f"SkillsLoader injection skipped: {e}")
        return ""

    async def _persist_turns_background(
        self,
        session_id: str,
        messages: List[Message],
        turn_offset: int,
        execution_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Stores conversation turns in EpisodicMemory as a background fire-and-forget task,
        and auto-indexes non-empty turns into VectorSearchEngine for semantic recall.
        Only called when episodic_memory is configured. Errors are caught and logged.
        """
        if self.episodic_memory is None:
            return
        try:
            for idx, msg in enumerate(messages):
                tool_calls_data = None
                if msg.tool_calls:
                    tool_calls_data = [
                        tc.model_dump() if hasattr(tc, "model_dump") else str(tc)
                        for tc in msg.tool_calls
                    ]
                msg_meta: Dict[str, Any] = {}
                if getattr(msg, "tool_call_id", None):
                    msg_meta["tool_call_id"] = msg.tool_call_id
                if getattr(msg, "name", None):
                    msg_meta["name"] = msg.name
                if msg.role == "assistant":
                    if execution_meta:
                        msg_meta.update(execution_meta)
                    else:
                        msg_meta.setdefault("tool_calls_count", len(msg.tool_calls or []))
                        msg_meta.setdefault("model_used", getattr(self, "model", getattr(self.router, "default_model", "hermes-agent")))
                        msg_meta.setdefault("latency_ms", 0.0)
                stored_turn_id = await self.episodic_memory.store_turn(
                    session_id=session_id,
                    turn_index=None,
                    role=msg.role,
                    content=msg.content or "",
                    tool_calls=tool_calls_data,
                    metadata=msg_meta if msg_meta else None,
                )
                # Auto-index turn into VectorSearchEngine (Step 21)
                if self.vector_search is not None and msg.content and len(msg.content.strip()) > 5:
                    doc_id = f"{session_id}:{stored_turn_id}:{msg.role}"
                    try:
                        await self.vector_search.add_document(
                            doc_id=doc_id,
                            text=f"[{msg.role}] {msg.content}",
                            metadata={"session_id": session_id, "turn": stored_turn_id, "role": msg.role},
                        )
                    except Exception as ve:
                        logger.debug(f"VectorSearch auto-indexing skipped for {doc_id}: {ve}")
        except Exception as e:
            logger.warning(f"EpisodicMemory persistence failed for session '{session_id}': {e}")

    async def _learn_preferences_background(
        self, user_message: str, assistant_response: Optional[str] = None
    ) -> None:
        """
        Background fire-and-forget task to extract and persist implicit user preferences post-turn.
        Only runs if preference_learner is active. Zero latency impact on main loop.
        """
        if self.preference_learner is None:
            return
        try:
            learned = await self.preference_learner.learn_from_turn(
                user_message=user_message,
                assistant_response=assistant_response,
            )
            if learned and self.telemetry:
                self.telemetry.emit_sync(
                    "preference.learned",
                    {"preference": learned, "source": "implicit_reflection"},
                )
        except Exception as e:
            logger.debug(f"Implicit preference learning skipped: {e}")

    async def run(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[Union[List[Dict[str, Any]], Any]] = None,
        tool_executor: Optional[Callable[..., Any]] = None,
        task: Optional[str] = None,
        max_turns: Optional[int] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        preferred_backend: Optional[str] = None,
        on_turn_end: Optional[Callable[[int, ProviderResponse], Any]] = None,
        session_id: Optional[str] = None,
        tool_tags: Optional[List[str]] = None,
        thinking_mode: Optional[str] = "on",
    ) -> EngineResult:
        """
        Runs the autonomous Hermes execution while-loop.

        Args:
            prompt: Optional user query string.
            messages: Optional existing conversation history.
            system_prompt: Custom system prompt instructions.
            tools: Tool declarations list or ToolRegistry duck-type with get_schemas().
            tool_executor: Tool dispatch function (name, args) -> result.
            task: Task cascade identifier for ParetoRouter (e.g. 'fast_chat', 'code').
            max_turns: Maximum allowed turns before triggering guardrail cutoff.
            temperature: Model sampling temperature.
            max_tokens: Maximum tokens for response generation.
            preferred_backend: Optional configured backend to try first while
                retaining normal availability and fallback behavior.
            on_turn_end: Optional callback invoked after each model turn.
            session_id: Optional session identifier for EpisodicMemory grouping.
            tool_tags: Optional tag filter to dynamically scope schemas from ToolRegistry.
            thinking_mode: Optional thinking control ('off', 'auto', 'on'). Defaults to 'on'.
        """
        start_time = time.monotonic()
        active_task = task or self.default_task
        limit_turns = max_turns if max_turns is not None else self.max_turns
        effective_system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

        # Resolve whether extended model thinking (Chain-of-Thought) should be enabled
        mode_norm = (thinking_mode or "on").strip().lower()
        if mode_norm in ("on", "true", "1", "enabled"):
            enable_thinking = True
        elif mode_norm == "auto":
            q_lower = (prompt or "").lower()
            enable_thinking = active_task == "deep_reasoning" or any(
                kw in q_lower
                for kw in ("step by step", "prove", "architect", "complex", "deep dive", "debug", "kyu", "why does")
            )
        else:
            enable_thinking = False

        # Telemetry: emit run_start
        if self.telemetry:
            self.telemetry.emit_sync(
                "engine.run_start",
                {"session_id": session_id, "task": active_task, "prompt": (prompt or "")[:100]},
            )

        # Memory & Skills context injection — run concurrently via asyncio.gather
        # Skip heavy ONNX embedding lookup on trivial ultra-short greetings (<12 chars)
        query_for_memory = (prompt or "").strip()
        is_trivial_greeting = len(query_for_memory) < 15 and query_for_memory.lower() in {
            "hi", "hello", "hey", "hii", "helo", "yo", "sup", "ok", "okay", "thanks", "thank you", "namaste", "aur batao"
        }
        mem_coro = (
            self._build_memory_context(query_for_memory if not is_trivial_greeting else "", session_id)
            if (self.state_memory is not None or self.vector_search is not None)
            else asyncio.sleep(0, result="")
        )
        skills_coro = (
            self._build_skills_context(query_for_memory)
            if (self.skills_loader is not None and query_for_memory and not is_trivial_greeting)
            else asyncio.sleep(0, result="")
        )
        memory_context, skills_section = await asyncio.gather(mem_coro, skills_coro)
        # LLM Prompt Caching Alignment (Static Prefix -> Dynamic Suffix):
        # Keep the immutable base system prompt at Byte 0 so OpenAI, Groq, DeepSeek, Gemini 2.5,
        # Anthropic/OpenRouter, and local Ollama KV-prefix caches achieve 100% hit rate on the
        # ~1,750-token core instructions + StateMemory prefix across turns and sub-turns.
        if memory_context:
            effective_system_prompt = effective_system_prompt + "\n\n---\n\n" + memory_context
        if skills_section:
            wrapped_skills = (
                skills_section
                if skills_section.strip().startswith("<skills>")
                else f"<skills>\n{skills_section}\n</skills>"
            )
            effective_system_prompt = effective_system_prompt + "\n\n---\n\n" + wrapped_skills

        # Resolve the complete currently enabled tool catalogue once for this request.
        # Done before history loading so tool schemas can be deducted from the token budget.
        # Primary schemas omit conditional fallback tools during normal turns;
        # the full catalogue is retained for explicit recovery turns after a miss/error.
        tool_catalog_schemas: Optional[List[Dict[str, Any]]] = None
        all_tool_catalog_schemas: Optional[List[Dict[str, Any]]] = None
        tool_metadata: Dict[str, Any] = {}
        effective_executor = tool_executor

        if tools is not None:
            if hasattr(tools, "get_schemas") and callable(tools.get_schemas):
                try:
                    sig = inspect.signature(tools.get_schemas)
                    if "tags" in sig.parameters and tool_tags is not None:
                        tool_catalog_schemas = tools.get_schemas(tags=tool_tags)
                    else:
                        tool_catalog_schemas = tools.get_schemas()
                except Exception:
                    tool_catalog_schemas = tools.get_schemas()
                if hasattr(tools, "get_all_schemas") and callable(tools.get_all_schemas):
                    try:
                        all_sig = inspect.signature(tools.get_all_schemas)
                        if "tags" in all_sig.parameters and tool_tags is not None:
                            all_tool_catalog_schemas = tools.get_all_schemas(tags=tool_tags)
                        else:
                            all_tool_catalog_schemas = tools.get_all_schemas()
                    except Exception as exc:
                        logger.debug("Full schema catalogue unavailable; recovery will use primary schemas: %s", exc)
                if effective_executor is None and hasattr(tools, "execute"):
                    effective_executor = tools.execute

                if hasattr(tools, "list_tools") and callable(tools.list_tools):
                    try:
                        available_objects = (
                            tools.list_tools(tags=tool_tags)
                            if tool_tags is not None
                            else tools.list_tools()
                        )
                        tool_metadata = {
                            str(getattr(tool_object, "name", "")): tool_object
                            for tool_object in available_objects
                            if getattr(tool_object, "name", None)
                        }
                    except Exception as exc:
                        logger.debug("Tool metadata lookup skipped: %s", exc)
            elif isinstance(tools, list):
                tool_catalog_schemas = tools
                all_tool_catalog_schemas = tools

        if tool_catalog_schemas:
            seen_names = set()
            deduped_schemas = []
            for schema in tool_catalog_schemas:
                if not isinstance(schema, dict):
                    continue
                if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
                    name = schema["function"].get("name")
                else:
                    name = schema.get("name")

                if name:
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                deduped_schemas.append(schema)

            # Preserve deterministic catalogue ordering for provider-side prefix caching.
            deduped_schemas.sort(
                key=lambda schema: (
                    schema.get("function", {}).get("name", "")
                    if isinstance(schema.get("function"), dict)
                    else schema.get("name", "")
                )
            )
            tool_catalog_schemas = deduped_schemas or None
        else:
            tool_catalog_schemas = None

        # Normalize the recovery catalogue separately: unlike normal schemas, it
        # intentionally includes conditional fallback tools but still preserves order.
        if all_tool_catalog_schemas:
            seen_all_names = set()
            deduped_all_schemas = []
            for schema in all_tool_catalog_schemas:
                if not isinstance(schema, dict):
                    continue
                function_schema = schema.get("function")
                schema_name = (
                    function_schema.get("name")
                    if isinstance(function_schema, dict)
                    else schema.get("name")
                )
                if schema_name:
                    if schema_name in seen_all_names:
                        continue
                    seen_all_names.add(schema_name)
                deduped_all_schemas.append(schema)
            deduped_all_schemas.sort(
                key=lambda schema: (
                    schema.get("function", {}).get("name", "")
                    if isinstance(schema.get("function"), dict)
                    else schema.get("name", "")
                )
            )
            all_tool_catalog_schemas = deduped_all_schemas or None
        else:
            all_tool_catalog_schemas = tool_catalog_schemas

        # Normalize working messages
        working_messages: List[Message] = []
        if messages:
            working_messages.extend(messages)
        elif session_id and self.episodic_memory is not None:
            # Rehydrate history from the actual remaining model context budget.
            # The current prompt, system prompt, tool schemas, completion reserve, and
            # safety headroom are deducted before any episodic rows are loaded.
            history_budget = self._calculate_history_token_budget(
                system_prompt=effective_system_prompt,
                current_prompt=prompt,
                tool_schemas=tool_catalog_schemas,
                active_task=active_task,
                preferred_backend=preferred_backend,
                max_output_tokens=max_tokens if max_tokens is not None else 4096,
            )
            if history_budget > 0:
                try:
                    try:
                        history_messages = await self.episodic_memory.get_recent_messages(
                            session_id=session_id,
                            max_tokens=history_budget,
                            token_counter=getattr(self.compressor, "counter", None),
                        )
                    except TypeError:
                        # Support adapters that accept max_tokens but not token_counter.
                        try:
                            history_messages = await self.episodic_memory.get_recent_messages(
                                session_id=session_id,
                                max_tokens=history_budget,
                            )
                        except TypeError:
                            # Do not fall back to a fixed message count: that could overflow
                            # the model context when the calculated history budget is small.
                            logger.warning(
                                "Episodic adapter for session '%s' does not support token-budget history loading; "
                                "skipping history to preserve the context limit.",
                                session_id,
                            )
                            history_messages = []
                    working_messages.extend(history_messages)
                    logger.info(
                        "Rehydrated %d history messages for session '%s' using token budget: %d tokens",
                        len(history_messages),
                        session_id,
                        history_budget,
                    )
                except Exception as exc:
                    logger.debug("Episodic history load skipped for %s: %s", session_id, exc)
            else:
                logger.info(
                    "Skipping episodic history for session '%s': no context tokens remain after fixed prompt/tool reserves.",
                    session_id,
                )

        # Track the first message created by this run so both the user prompt
        # and the resulting assistant/tool turns are persisted.
        messages_before = len(working_messages)
        # Keep an append-only ledger of messages produced by this run. The working
        # history may later be compressed, so persistence must not rely on its indices.
        run_messages: List[Message] = []
        if prompt:
            user_message = Message(role="user", content=prompt)
            working_messages.append(user_message)
            run_messages.append(user_message)

        if not working_messages:
            raise ValueError("HermesAgentEngine requires either 'prompt' or non-empty 'messages'.")

        turn = 0
        total_tool_calls = 0
        total_cached_tokens = 0
        last_model_used = ""
        last_finish_reason = "stop"
        last_batch_signature = ""
        consecutive_identical_batches = 0
        signature_history: List[str] = []
        force_synthesis_next_turn = False
        force_full_tool_catalog_next_turn = False

        # Hermes Autonomous While-Loop
        while turn < limit_turns:
            turn += 1
            logger.debug(f"Starting Hermes engine turn {turn}/{limit_turns}")

            # 0. 100% Immutable System Prompt for Perfect KV-Cache Prefix Reuse
            turn_system_prompt = effective_system_prompt
            browser_state_block = ""
            try:
                from makima.tools.browser.automation import get_browser_controller
                browser_summary = get_browser_controller().get_active_context_summary()
                if browser_summary:
                    browser_state_block = f"\n\n<active_browser_state>\n{browser_summary}\n</active_browser_state>"
            except Exception:
                pass

            # 1. Dynamic Context Compression Check
            current_model = last_model_used or preferred_backend
            # Turn-1 fix: last_model_used is empty on the first turn, so probe the router
            # to get the actual model name and context_limit for correct compression detection.
            # We read config.context_limit directly from BackendConfig (set in settings.yaml)
            # rather than relying on a hardcoded model-name→limit table, so user YAML wins.
            turn1_context_limit: Optional[int] = None
            if not current_model and self.router is not None:
                try:
                    top_candidates = self.router.get_ranked_candidates(active_task)
                    if top_candidates:
                        top_config = top_candidates[0].provider.config
                        current_model = getattr(top_config, "model", None) or ""
                        raw_limit = getattr(top_config, "context_limit", None)
                        if raw_limit and isinstance(raw_limit, int) and raw_limit > 0:
                            turn1_context_limit = raw_limit
                except Exception:
                    pass  # Graceful degradation: compressor falls back to 128K default

            if self.compressor.needs_compression(
                working_messages,
                system_prompt=turn_system_prompt,
                model=current_model,
                max_tokens=turn1_context_limit,
            ):
                logger.info(f"Context exceeds budget at turn {turn}. Performing middle-turn compression.")
                working_messages = self.compressor.compress(
                    working_messages,
                    system_prompt=turn_system_prompt,
                    model=current_model,
                    max_tokens=turn1_context_limit,
                )

            # 2. Query provider along Pareto frontier with automatic failover
            active_tools_for_turn = tool_catalog_schemas
            if force_full_tool_catalog_next_turn:
                active_tools_for_turn = all_tool_catalog_schemas or tool_catalog_schemas
                logger.warning(
                    "Expanding tool schemas to the full enabled catalogue after a hidden-tool request or tool failure."
                )
                force_full_tool_catalog_next_turn = False
            elif active_tools_for_turn:
                selection_context = self._tool_selection_context(prompt, working_messages)
                active_tools_for_turn = await self.tool_selector.select_schemas(
                    tool_catalog_schemas,
                    selection_context,
                    tool_metadata=tool_metadata,
                )

            # When active tools are provided to the model, strictly clamp temperature
            # to 0.0 to guarantee deterministic tool selection and exact parameter formatting,
            # eliminating random token sampling drift. For pure conversational turns (no tools),
            # respect the requested temperature.
            turn_temperature = 0.0 if active_tools_for_turn else temperature

            # Transiently attach active_browser_state to the very last message for KV-cache preservation
            # (keeps permanent working_messages history untainted and system prompt prefix 100% static)
            messages_for_llm = list(working_messages)
            if browser_state_block and messages_for_llm:
                last_m = messages_for_llm[-1]
                messages_for_llm[-1] = Message(
                    role=last_m.role,
                    content=(last_m.content or "") + browser_state_block,
                    name=getattr(last_m, "name", None),
                    tool_call_id=getattr(last_m, "tool_call_id", None),
                    tool_calls=getattr(last_m, "tool_calls", None),
                )

            router_kwargs: Dict[str, Any] = {
                "task": active_task,
                "messages": messages_for_llm,
                "system_prompt": turn_system_prompt,
                "tools": active_tools_for_turn,
                "temperature": turn_temperature,
                "max_tokens": max_tokens,
            }
            if force_synthesis_next_turn:
                active_tools_for_turn = None
                router_kwargs["tools"] = None
                router_kwargs["tool_choice"] = "none"
                router_kwargs["force_synthesis"] = True
                turn_system_prompt = (
                    f"{turn_system_prompt}\n\n"
                    "[SYSTEM DIRECTIVE: Repeated tool invocations detected. "
                    "Do NOT call any more tools. Synthesize a complete, accurate final response for the user "
                    "right now using the existing gathered information. "
                    "CRITICAL: Do NOT output a greeting (e.g. 'Hello, kya kaam hai aaj?'). You MUST report "
                    "what tools were executed, what was observed or found, and address the user's request directly.]"
                )
                router_kwargs["system_prompt"] = turn_system_prompt
            # Keep compatibility with lightweight test routers and third-party
            # integrations that predate backend pinning.
            if preferred_backend:
                router_kwargs["preferred_backend"] = preferred_backend
            if thinking_mode is not None:
                router_kwargs["enable_thinking"] = enable_thinking
            response: ProviderResponse = await self.router.execute_with_fallback(**router_kwargs)

            last_model_used = response.model
            last_finish_reason = response.finish_reason
            if response.usage and isinstance(response.usage, dict):
                total_cached_tokens += int(response.usage.get("cached_tokens", 0) or 0)

            # 3. Append assistant response turn to working history
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls if response.tool_calls else None,
            )
            working_messages.append(assistant_msg)
            run_messages.append(assistant_msg)

            # Optional turn-end observer hook
            if on_turn_end:
                cb_res = on_turn_end(turn, response)
                if inspect.isawaitable(cb_res):
                    await cb_res

            # Plain-text tool traces are untrusted model output, never executable actions.
            # Only provider-native structured tool_calls may reach dispatch.
            if not response.tool_calls and response.content and "[Executed Tools in Turn:" in response.content:
                logger.warning(
                    "Ignored a plain-text tool execution trace in turn %d; no structured tool call was returned.",
                    turn,
                )
                clean_content = self._strip_spoofed_tool_traces(response.content)
                if clean_content:
                    response.content = (
                        clean_content
                        + "\n\n[No action was executed: the model returned a plain-text tool trace, "
                        "not a structured tool call.]"
                    )
                else:
                    response.content = (
                        "No action was executed because the model returned a plain-text tool trace "
                        "instead of a structured tool call."
                    )
                assistant_msg.content = response.content

            # Finalize only when the provider returned no structured tool calls.
            if not response.tool_calls:
                elapsed_ms = (time.monotonic() - start_time) * 1000.0
                final_content = response.content or ""
                # Redact any secrets in final model output
                sanitized_content = self.guardrails.filter_secrets(final_content)
                clean_content, suggestions = self._extract_suggestions(sanitized_content)
                clean_content = self._sanitize_degenerate_post_tool_greeting(
                    clean_content, working_messages, total_tool_calls
                )
                assistant_msg.content = clean_content

                result = EngineResult(
                    content=clean_content,
                    messages=working_messages,
                    turn_count=turn,
                    tool_calls_executed=total_tool_calls,
                    completed=True,
                    finish_reason=last_finish_reason,
                    model_used=last_model_used,
                    latency_ms=elapsed_ms,
                    cached_tokens=total_cached_tokens,
                    suggestions=suggestions,
                )

                # Fire-and-forget: persist new turns to EpisodicMemory
                if session_id and self.episodic_memory is not None:
                    new_msgs = list(run_messages)
                    exec_meta = {
                        "tool_calls_count": total_tool_calls,
                        "model_used": last_model_used,
                        "latency_ms": elapsed_ms,
                    }
                    task_ref = asyncio.create_task(
                        self._persist_turns_background(
                            session_id, new_msgs, messages_before, execution_meta=exec_meta
                        )
                    )
                    self._background_tasks.add(task_ref)
                    task_ref.add_done_callback(self._background_tasks.discard)

                # Fire-and-forget: learn implicit user preferences post-turn
                if self.preference_learner is not None:
                    latest_user = next((m.content for m in reversed(working_messages) if m.role == "user"), None)
                    if latest_user:
                        pref_task = asyncio.create_task(
                            self._learn_preferences_background(latest_user, sanitized_content)
                        )
                        self._background_tasks.add(pref_task)
                        pref_task.add_done_callback(self._background_tasks.discard)

                if self.telemetry:
                    self.telemetry.emit_sync(
                        "engine.run_complete",
                        {
                            "session_id": session_id,
                            "turn_count": turn,
                            "tool_calls_executed": total_tool_calls,
                            "latency_ms": round(elapsed_ms, 2),
                            "cached_tokens": total_cached_tokens,
                            "model": last_model_used,
                            "completed": True,
                        },
                    )

                return result

            # 5. Dispatch tools under the configured concurrency policy.
            concurrency_enabled = True
            max_parallel_tools = 8
            try:
                from makima.config import get_settings
                concurrency_cfg = get_settings().tools.concurrency
                concurrency_enabled = bool(concurrency_cfg.enabled)
                max_parallel_tools = max(1, int(concurrency_cfg.max_concurrency))
            except Exception as exc:
                logger.debug("Tool concurrency settings unavailable; using safe defaults: %s", exc)
            parallel_semaphore = asyncio.Semaphore(max_parallel_tools)

            def _is_call_parallel_safe(call_name: str) -> bool:
                if not concurrency_enabled:
                    return False
                # A caller-provided schema list/custom executor does not inherit safety flags
                # from the unrelated global registry.
                if tools is not None:
                    if hasattr(tools, "is_parallel_safe") and callable(tools.is_parallel_safe):
                        try:
                            return bool(tools.is_parallel_safe(call_name))
                        except Exception as exc:
                            logger.debug("Tool parallel-safety lookup failed for %s: %s", call_name, exc)
                    return False
                try:
                    from makima.tools import get_registry
                    reg = get_registry()
                    if reg is not None and hasattr(reg, "is_parallel_safe"):
                        return bool(reg.is_parallel_safe(call_name))
                except Exception:
                    pass
                return False

            # Strict per-turn allowlist: if no schemas were exposed, no tool call is executable.
            active_tool_names: Set[str] = set()
            for schema in active_tools_for_turn or []:
                if not isinstance(schema, dict):
                    continue
                function_schema = schema.get("function")
                candidate_name = (
                    function_schema.get("name")
                    if isinstance(function_schema, dict)
                    else schema.get("name")
                )
                if candidate_name:
                    active_tool_names.add(str(candidate_name))

            def _canonical_tool_name(name: str) -> str:
                return name.split(":")[-1] if ":" in name else name

            full_catalog_names: Set[str] = set()
            for schema in all_tool_catalog_schemas or tool_catalog_schemas or []:
                if not isinstance(schema, dict):
                    continue
                function_schema = schema.get("function")
                candidate_name = (
                    function_schema.get("name")
                    if isinstance(function_schema, dict)
                    else schema.get("name")
                )
                if candidate_name:
                    full_catalog_names.add(str(candidate_name))

            hidden_registered_calls = {
                _canonical_tool_name(call.name)
                for call in response.tool_calls
                if active_tools_for_turn is not None
                and _canonical_tool_name(call.name) in full_catalog_names
                and _canonical_tool_name(call.name) not in active_tool_names
            }
            if hidden_registered_calls:
                force_full_tool_catalog_next_turn = True
                logger.warning(
                    "Model requested registered tools omitted by semantic retrieval: %s. "
                    "The calls are blocked for this turn; the full catalogue will be exposed next turn.",
                    sorted(hidden_registered_calls),
                )

            batches: List[Tuple[bool, List[Tuple[int, ToolCall]]]] = []
            curr_items: List[Tuple[int, ToolCall]] = []
            curr_safe: bool = False

            for idx, call in enumerate(response.tool_calls):
                call_safe = _is_call_parallel_safe(call.name)
                if not curr_items:
                    curr_items = [(idx, call)]
                    curr_safe = call_safe
                elif call_safe and curr_safe:
                    curr_items.append((idx, call))
                else:
                    batches.append((curr_safe, curr_items))
                    curr_items = [(idx, call)]
                    curr_safe = call_safe
            if curr_items:
                batches.append((curr_safe, curr_items))

            ordered_outputs: List[Optional[str]] = [None] * len(response.tool_calls)

            for is_safe, batch in batches:
                if is_safe and len(batch) > 1:
                    names_log = [c.name for _, c in batch]
                    logger.debug(f"Executing {len(batch)} parallel-safe tool calls concurrently: {names_log}")
                    async def _execute_parallel_limited(tool_call: ToolCall) -> str:
                        async with parallel_semaphore:
                            return await self._execute_tool_call(
                                tool_call,
                                effective_executor,
                                allowed_tool_names=active_tool_names,
                            )

                    tasks = [_execute_parallel_limited(c) for _, c in batch]
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for (orig_idx, c), res in zip(batch, batch_results):
                        total_tool_calls += 1
                        if isinstance(res, Exception):
                            output_str = f"[TOOL_FAILED: {c.name}] {type(res).__name__}: {str(res)}"
                        else:
                            output_str = str(res)
                        ordered_outputs[orig_idx] = output_str
                else:
                    for orig_idx, c in batch:
                        total_tool_calls += 1
                        logger.debug(f"Executing tool call sequentially: {c.name} (id={c.id})")
                        tool_output = await self._execute_tool_call(c, effective_executor, allowed_tool_names=active_tool_names)
                        ordered_outputs[orig_idx] = tool_output

            # If a primary tool returns a clear operational failure, expose the full
            # enabled catalogue on the next turn so a registered fallback can be selected.
            def _tool_output_signals_failure(output: Optional[str]) -> bool:
                text = output or ""
                if text.startswith(("[TOOL_FAILED:", "[TOOL_NOT_AVAILABLE:", "[TOOL_NOT_FOUND:")):
                    return True
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError):
                    return False
                if not isinstance(payload, dict):
                    return False
                status = str(payload.get("status") or "").strip().lower()
                return (
                    payload.get("success") is False
                    or bool(payload.get("error"))
                    or status in {"error", "failed", "failure"}
                )

            if any(_tool_output_signals_failure(output) for output in ordered_outputs):
                force_full_tool_catalog_next_turn = True

            # Multi-pattern tool invocation loop detection
            try:
                curr_sig = json.dumps(
                    [(c.name, c.arguments or {}) for c in response.tool_calls],
                    sort_keys=True,
                    default=str,
                )
            except Exception:
                curr_sig = str([(c.name, str(c.arguments)) for c in response.tool_calls])

            if curr_sig == last_batch_signature:
                consecutive_identical_batches += 1
            else:
                last_batch_signature = curr_sig
                consecutive_identical_batches = 1

            signature_history.append(curr_sig)

            # Loop detection conditions:
            # 1. 3 identical consecutive batches (A -> A -> A)
            # 2. Same batch signature appearing >= 3 times across the session
            # 3. Oscillating 2-step cycle (A -> B -> A -> B)
            is_loop_detected = False
            loop_reason = ""

            if consecutive_identical_batches >= 3:
                is_loop_detected = True
                loop_reason = f"invoked the exact same tool call(s) {consecutive_identical_batches} times consecutively"
            elif signature_history.count(curr_sig) >= 3:
                is_loop_detected = True
                loop_reason = f"repeated the same tool call combination {signature_history.count(curr_sig)} times"
            elif (
                len(signature_history) >= 4
                and signature_history[-1] == signature_history[-3]
                and signature_history[-2] == signature_history[-4]
            ):
                is_loop_detected = True
                loop_reason = "oscillating between alternating tool calls without making forward progress"

            loop_notice = ""
            if is_loop_detected:
                loop_notice = (
                    f"\n[SYSTEM NOTICE: Loop detected — you are {loop_reason}. "
                    f"Do NOT call any more tools. Synthesize your final answer now using the existing output.]"
                )
                force_synthesis_next_turn = True

            for call, output_str in zip(response.tool_calls, ordered_outputs):
                tool_msg = Message(
                    role="tool",
                    content=(output_str or "") + loop_notice,
                    tool_call_id=call.id,
                    name=call.name,
                )
                working_messages.append(tool_msg)
                run_messages.append(tool_msg)

        # 5b. Final Synthesis Pass on turn limit: give the LLM one tool-free pass to summarize
        # all gathered tool results into a helpful answer rather than discarding work.
        try:
            synthesis_prompt = (
                f"{effective_system_prompt}\n\n"
                "[SYSTEM DIRECTIVE: Maximum tool-execution turns reached. Do NOT call any more tools. "
                "Synthesize a complete, accurate, and comprehensive final response for the user right now based on "
                "all the tool results gathered above. "
                "CRITICAL: Do NOT output a greeting (e.g. 'Hello, kya kaam hai aaj?'). You MUST report "
                "what tools were executed, what was observed or found, and address the user's request directly.]"
            )
            synth_kwargs: Dict[str, Any] = {
                "task": active_task,
                "messages": working_messages,
                "system_prompt": synthesis_prompt,
                "tools": None,
                "tool_choice": "none",
                "force_synthesis": True,
                "temperature": 0.0,
                "max_tokens": max_tokens,
            }
            if preferred_backend:
                synth_kwargs["preferred_backend"] = preferred_backend
            synth_resp: ProviderResponse = await self.router.execute_with_fallback(**synth_kwargs)
            if not synth_resp.tool_calls and synth_resp.content and synth_resp.content.strip():
                elapsed_ms = (time.monotonic() - start_time) * 1000.0
                sanitized_content = self.guardrails.filter_secrets(synth_resp.content)
                clean_content, suggestions = self._extract_suggestions(sanitized_content)
                clean_content = self._sanitize_degenerate_post_tool_greeting(
                    clean_content, working_messages, total_tool_calls
                )
                synthesis_message = Message(role="assistant", content=clean_content)
                working_messages.append(synthesis_message)
                run_messages.append(synthesis_message)

                if session_id and self.episodic_memory is not None:
                    new_msgs = list(run_messages)
                    synth_meta = {
                        "tool_calls_count": total_tool_calls,
                        "model_used": synth_resp.model or last_model_used,
                        "latency_ms": elapsed_ms,
                    }
                    task_ref = asyncio.create_task(
                        self._persist_turns_background(
                            session_id, new_msgs, messages_before, execution_meta=synth_meta
                        )
                    )
                    self._background_tasks.add(task_ref)
                    task_ref.add_done_callback(self._background_tasks.discard)

                return EngineResult(
                    content=clean_content,
                    messages=working_messages,
                    turn_count=turn,
                    tool_calls_executed=total_tool_calls,
                    completed=True,
                    finish_reason=synth_resp.finish_reason or "stop",
                    model_used=synth_resp.model or last_model_used,
                    latency_ms=elapsed_ms,
                    cached_tokens=total_cached_tokens,
                    suggestions=suggestions,
                )
        except Exception as synth_exc:
            logger.debug(f"Final synthesis pass skipped after max_turns: {synth_exc}")

        # 6. Max turns guard reached without model terminating
        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        # If model failed to synthesize, build grounded summary from executed tools
        observed_summaries = []
        for m in reversed(working_messages):
            if m.role == "tool" and m.content:
                text_snippet = m.content[:160].replace("\n", " ").strip()
                if text_snippet and text_snippet not in observed_summaries:
                    observed_summaries.append(text_snippet)
                if len(observed_summaries) >= 3:
                    break
        if observed_summaries:
            cutoff_message = (
                f"[MAX_TURNS_EXCEEDED] Execution reached turn limit ({limit_turns}) "
                f"after executing {total_tool_calls} tool calls. "
                f"Observed outputs: {' | '.join(reversed(observed_summaries))}"
            )
        else:
            cutoff_message = (
                f"[MAX_TURNS_EXCEEDED] Execution reached turn limit ({limit_turns}) "
                f"after executing {total_tool_calls} tool calls without final completion."
            )
        logger.warning(cutoff_message)

        result = EngineResult(
            content=cutoff_message,
            messages=working_messages,
            turn_count=turn,
            tool_calls_executed=total_tool_calls,
            completed=False,
            finish_reason="max_turns",
            model_used=last_model_used,
            latency_ms=elapsed_ms,
            cached_tokens=total_cached_tokens,
            error=cutoff_message,
        )

        # Fire-and-forget: persist new turns even on max_turns cutoff
        if session_id and self.episodic_memory is not None:
            new_msgs = list(run_messages)
            cutoff_meta = {
                "tool_calls_count": total_tool_calls,
                "model_used": last_model_used,
                "latency_ms": elapsed_ms,
            }
            task_ref = asyncio.create_task(
                self._persist_turns_background(
                    session_id, new_msgs, messages_before, execution_meta=cutoff_meta
                )
            )
            self._background_tasks.add(task_ref)
            task_ref.add_done_callback(self._background_tasks.discard)

        # Fire-and-forget: learn implicit user preferences post-turn
        if self.preference_learner is not None:
            latest_user = next((m.content for m in reversed(working_messages) if m.role == "user"), None)
            if latest_user:
                pref_task = asyncio.create_task(
                    self._learn_preferences_background(latest_user, cutoff_message)
                )
                self._background_tasks.add(pref_task)
                pref_task.add_done_callback(self._background_tasks.discard)

        if self.telemetry:
            self.telemetry.emit_sync(
                "engine.run_complete",
                {
                    "session_id": session_id,
                    "turn_count": turn,
                    "tool_calls_executed": total_tool_calls,
                    "latency_ms": round(elapsed_ms, 2),
                    "model": last_model_used,
                    "completed": False,
                    "error": cutoff_message,
                },
            )

        return result
