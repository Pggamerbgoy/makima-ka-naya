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
    manage_memory,
    remember_user_preference,
    remember_fact,
    forget_user_preference,
    forget_fact,
    get_user_profile,
    get_memory_facts,
)
from makima.tools.web_search import (
    SearchResultList,
    deep_web_research,
    fetch_page,
    search_in_native_browser,
    web_search,
)
from makima.tools.messaging import (
    check_whatsapp_status,
    send_whatsapp_message,
    summarize_inbox,
)
from makima.tools.git import (
    git_commit,
    git_diff,
    git_log,
    git_status,
)
from makima.tools.os import (
    find_process_by_port,
    free_port,
    launch_application,
    snap_window,
)
from makima.tools.desktop import (
    clear_clipboard,
    computer_use,
    get_clipboard_text,
    set_clipboard_text,
)

__all__ = [
    # Core Registry & Decorator
    "Tool",
    "ToolError",
    "ToolNotFoundError",
    "ToolValidationError",
    "ToolExecutionError",
    "ToolRegistry",
    "get_registry",
    "reset_registry",
    "tool",
    # Consolidated Execution & Automation Tools
    "execute_command",
    "launch_application",
    "computer_use",
    "snap_window",
    "find_process_by_port",
    "free_port",
    "get_clipboard_text",
    "set_clipboard_text",
    "clear_clipboard",
    # Local Git Version Control Tools
    "git_status",
    "git_diff",
    "git_commit",
    "git_log",
    # Messaging & WhatsApp Tools
    "send_whatsapp_message",
    "check_whatsapp_status",
    "summarize_inbox",
    # Consolidated Web Search & Research
    "web_search",
    "fetch_page",
    "deep_web_research",
    "search_in_native_browser",
    "SearchResultList",
    # Consolidated Memory & Profile
    "manage_memory",
    "remember_user_preference",
    "remember_fact",
    "forget_user_preference",
    "forget_fact",
    "get_user_profile",
    "get_memory_facts",
]
