"""
Makima v2 — Tools Package.
Auto-discovering modular toolsets, @tool decorators, dynamic schema synthesis, and execution sandboxes.
"""

from makima.tools.registry import (
    Tool,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    get_registry,
    reset_registry,
    tool,
)
from makima.tools.terminal import execute_command
from makima.tools.memory import (
    remember_user_preference,
    remember_fact,
    forget_user_preference,
    forget_fact,
    get_user_profile,
    get_memory_facts,
)

__all__ = [
    "Tool",
    "ToolError",
    "ToolNotFoundError",
    "ToolValidationError",
    "ToolExecutionError",
    "ToolRegistry",
    "get_registry",
    "reset_registry",
    "tool",
    "execute_command",
    "remember_user_preference",
    "remember_fact",
    "forget_user_preference",
    "forget_fact",
    "get_user_profile",
    "get_memory_facts",
]

