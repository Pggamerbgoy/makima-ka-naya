"""
Makima v2 — Rich Interactive Command-Line Interface.
Hermes-style interactive chat REPL, tool registry inspection, system status diagnostics, and gateway supervisor.
"""

from typing import Any

def cli_main(*args: Any, **kwargs: Any) -> int:
    """Entrypoint for Makima v2 CLI."""
    from makima.cli.main import cli_main as _cli_main
    return _cli_main(*args, **kwargs)

__all__ = ["cli_main"]
