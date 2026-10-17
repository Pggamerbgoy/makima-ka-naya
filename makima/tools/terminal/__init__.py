"""
Makima v2 — Sandboxed Terminal & ConPTY Runner Package.
Architectural Pattern: Dual Batch Execution & Interactive ConPTY Terminal Engine.
Zero-Hardcoding Guarantee: Fully dynamic paths, safety guardrail interception, and pywinpty integration.
"""

from makima.tools.terminal.conpty import (
    ConPTYError,
    ConPTYManager,
    ConPTYNotSupportedError,
    ConPTYSession,
    get_conpty_manager,
    strip_ansi_escapes,
)
from makima.tools.terminal.runner import (
    CommandTimeoutError,
    clamp_to_workspace,
    execute_command,
    get_workspace_dir,
    truncate_output,
)

__all__ = [
    "execute_command",
    "CommandTimeoutError",
    "clamp_to_workspace",
    "get_workspace_dir",
    "truncate_output",
    "ConPTYSession",
    "ConPTYManager",
    "get_conpty_manager",
    "strip_ansi_escapes",
    "ConPTYError",
    "ConPTYNotSupportedError",
]
