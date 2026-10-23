"""
Makima v2 — Autonomous Command Line Interface (CLI).
Architectural Pattern: Clean, modular Hermes-style CLI powered by stdlib argparse and Rich.
Zero-Hardcoding Guarantee: Fully dynamic system discovery, zero static OS paths, and Pareto routing.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import psutil
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from makima.config import MakimaSettings, get_settings
from makima.core.engine import HermesAgentEngine
from makima.gateway.daemon import GatewayDaemon
from makima.memory import EpisodicMemory, StateMemory
from makima.provider.adapters.base import Message, ProviderResponse
from makima.runtime import build_engine, build_registry
from makima.tools.registry import Tool, ToolRegistry, get_registry

logger = logging.getLogger("makima.cli")


def _safe_reconfigure_streams() -> None:
    """Configures stdout and stderr to handle UTF-8 cleanly across Windows terminals."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# -----------------------------------------------------------------------------
# 1. Tools List Formatter
# -----------------------------------------------------------------------------

def render_tools_table(
    tools: Sequence[Tool],
    console: Console,
    filter_tag: Optional[str] = None,
) -> None:
    """Renders registered tools in a structured, beautifully styled Rich Table."""
    title_suffix = f" (Filter: tag='{escape(filter_tag)}')" if filter_tag else ""
    table = Table(
        title=f"[bold cyan]Makima Registered Tools{title_suffix}[/bold cyan]",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_column("Tags", style="magenta")
    table.add_column("Parameters", style="green")

    for t in sorted(tools, key=lambda x: x.name):
        # Format tags safely without triggering Rich markup tags
        tags_str = ", ".join(f"#{tag}" for tag in t.tags) if t.tags else "[dim]none[/dim]"

        # Format parameters schema
        props: Dict[str, Any] = t.parameters_schema.get("properties", {})
        required_fields = set(t.parameters_schema.get("required", []))
        param_entries: List[str] = []

        for p_name, p_info in props.items():
            p_type = p_info.get("type")
            if not p_type and "anyOf" in p_info:
                types = [sub.get("type", "any") for sub in p_info["anyOf"]]
                p_type = " | ".join(types)
            p_type = p_type or "any"

            default_val = p_info.get("default", ...)
            def_str = f" = {default_val}" if default_val is not ... else ""
            req_mark = "[bold red]*[/bold red]" if p_name in required_fields else "[dim](opt)[/dim]"
            param_entries.append(
                f"[bold]{escape(p_name)}[/bold]: [yellow]{escape(p_type)}[/yellow]{escape(def_str)} {req_mark}"
            )

        params_display = "\n".join(param_entries) if param_entries else "[dim]None[/dim]"

        # Strip multi-line docstring down to clean display
        desc_lines = t.description.strip().splitlines()
        clean_desc = desc_lines[0].strip() if desc_lines else t.name

        table.add_row(t.name, clean_desc, tags_str, params_display)

    console.print(table)
    console.print(f"[dim]Total registered tools: {len(tools)}[/dim]\n")


def tools_list_command(
    args: Any,
    console: Console,
    registry: Optional[ToolRegistry] = None,
) -> int:
    """Executes 'tools list' subcommand."""
    reg = registry or get_registry(auto_discover=True)
    tag = getattr(args, "tag", None)
    tools = reg.list_tools(tags=[tag] if tag else None)

    if not tools:
        if tag:
            console.print(f"[yellow]No tools found matching tag '{escape(tag)}'.[/yellow]")
        else:
            console.print("[yellow]No tools registered in registry.[/yellow]")
        return 0

    render_tools_table(tools, console=console, filter_tag=tag)
    return 0


# -----------------------------------------------------------------------------
# 2. System Status & Diagnostic Dashboard
# -----------------------------------------------------------------------------

def render_status_dashboard(
    settings: Optional[MakimaSettings] = None,
    console: Optional[Console] = None,
) -> None:
    """Renders comprehensive diagnostics including system resources, model backends, and memory state."""
    con = console or Console()
    cfg = settings or get_settings()

    # 1. System Resources Table
    sys_table = Table(
        title="[bold cyan]1. Host System Resources[/bold cyan]",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )
    sys_table.add_column("Component", style="bold cyan")
    sys_table.add_column("Diagnostics", style="white")

    # Host info
    sys_table.add_row(
        "Platform / OS",
        f"{platform.system()} {platform.release()} (Architecture: {platform.machine()})",
    )
    sys_table.add_row(
        "Python Runtime",
        f"{platform.python_version()} ({platform.python_implementation()}) [dim]{sys.executable}[/dim]",
    )

    # CPU & Memory
    cpu_percent = psutil.cpu_percent(interval=0.05)
    phys_cores = psutil.cpu_count(logical=False)
    log_cores = psutil.cpu_count(logical=True)
    sys_table.add_row(
        "CPU Load",
        f"{cpu_percent}% [dim]({phys_cores} Physical / {log_cores} Logical Cores)[/dim]",
    )

    mem = psutil.virtual_memory()
    mem_used = mem.used / (1024 ** 3)
    mem_total = mem.total / (1024 ** 3)
    sys_table.add_row(
        "System RAM",
        f"{mem_used:.1f} / {mem_total:.1f} GB ({mem.percent}% used) [dim]{mem.available / (1024 ** 3):.1f} GB available[/dim]",
    )

    # Disk
    try:
        disk_target = cfg.data_dir_path if cfg.data_dir_path.exists() else Path.home()
        disk = psutil.disk_usage(str(disk_target))
        disk_used = disk.used / (1024 ** 3)
        disk_total = disk.total / (1024 ** 3)
        sys_table.add_row(
            "Disk Storage",
            f"{disk_used:.1f} / {disk_total:.1f} GB ({disk.percent}% used) [dim]Free: {disk.free / (1024 ** 3):.1f} GB[/dim]",
        )
    except Exception as exc:
        sys_table.add_row("Disk Storage", f"[yellow]Failed to inspect: {exc}[/yellow]")

    # Process RSS
    proc = psutil.Process()
    rss_mb = proc.memory_info().rss / (1024 ** 2)
    sys_table.add_row("Process Memory", f"{rss_mb:.1f} MB RSS [dim](PID: {proc.pid})[/dim]")

    con.print(sys_table)

    # 2. Providers & Pareto Frontier Table
    prov_table = Table(
        title="[bold cyan]2. Model Providers & Zero-Cost Routing[/bold cyan]",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )
    prov_table.add_column("Backend", style="bold cyan")
    prov_table.add_column("Adapter", style="white")
    prov_table.add_column("Model Identifier", style="yellow")
    prov_table.add_column("Latency Tier", style="dim")
    prov_table.add_column("Credential Env", style="dim")
    prov_table.add_column("Status", style="bold")

    for name, backend in cfg.providers.backends.items():
        is_ready = backend.is_available
        if is_ready:
            status_text = "[bold green][READY][/bold green]"
        else:
            status_text = "[bold yellow][NO KEY][/bold yellow]"

        prov_table.add_row(
            name,
            backend.adapter,
            backend.model,
            backend.latency_tier,
            backend.api_key_env or "N/A (Local)",
            status_text,
        )

    con.print(prov_table)

    # Cascades Summary
    cascade_lines = [
        f"  - [bold]{task}[/bold]: {' -> '.join(chain)}"
        for task, chain in cfg.providers.cascades.items()
    ]
    con.print(
        Panel(
            "\n".join(cascade_lines),
            title="[bold cyan]Task Routing Cascades[/bold cyan]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    # 3. Dual-Tier Memory Diagnostics
    mem_diag_table = Table(
        title="[bold cyan]3. Dual-Tier Memory Engine State[/bold cyan]",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )
    mem_diag_table.add_column("Memory Layer", style="bold cyan")
    mem_diag_table.add_column("Location & Status", style="white")

    # State Memory (Tier 1)
    state_mem = StateMemory()
    mem_file = state_mem.memory_path
    user_file = state_mem.user_path

    if mem_file.is_file():
        mem_info = f"[green]FOUND[/green] [dim]({mem_file.stat().st_size} bytes, {len(mem_file.read_text(encoding='utf-8').splitlines())} lines)[/dim]"
    else:
        mem_info = "[yellow]PENDING TEMPLATE[/yellow]"

    if user_file.is_file():
        user_info = f"[green]FOUND[/green] [dim]({user_file.stat().st_size} bytes, {len(user_file.read_text(encoding='utf-8').splitlines())} lines)[/dim]"
    else:
        user_info = "[yellow]PENDING TEMPLATE[/yellow]"

    mem_diag_table.add_row("Tier 1: MEMORY.md", f"{mem_file}\n  Status: {mem_info}")
    mem_diag_table.add_row("Tier 1: USER.md", f"{user_file}\n  Status: {user_info}")

    # Episodic Memory (Tier 2)
    ep_mem = EpisodicMemory()
    db_file = Path(ep_mem.db_path) if ep_mem.db_path != ":memory:" else None

    if db_file and db_file.is_file():
        db_size_kb = db_file.stat().st_size / 1024.0
        turns_count = 0
        try:
            import sqlite3
            with sqlite3.connect(str(db_file)) as sq_conn:
                cur = sq_conn.cursor()
                cur.execute("SELECT count(*) FROM conversation_turns")
                turns_count = cur.fetchone()[0]
            ep_status = f"[green]ACTIVE[/green] [dim]({turns_count} turns recorded, {db_size_kb:.1f} KB, FTS5={ep_mem.fts_enabled})[/dim]"
        except Exception:
            ep_status = f"[green]ACTIVE[/green] [dim]({db_size_kb:.1f} KB, FTS5={ep_mem.fts_enabled})[/dim]"
    else:
        ep_status = f"[yellow]NOT INITIALIZED (0 turns, FTS5={ep_mem.fts_enabled})[/yellow]"

    mem_diag_table.add_row(
        "Tier 2: Episodic SQLite",
        f"{ep_mem.db_path}\n  Status: {ep_status}",
    )

    con.print(mem_diag_table)
    con.print()


def status_command(args: Any, console: Console) -> int:
    """Executes 'status' subcommand."""
    render_status_dashboard(console=console)
    return 0


# -----------------------------------------------------------------------------
# 3. Gateway Daemon Command
# -----------------------------------------------------------------------------

def setup_gateway_daemon(
    host: Optional[str] = None,
    port: Optional[int] = None,
    settings: Optional[MakimaSettings] = None,
) -> GatewayDaemon:
    """Constructs and configures GatewayDaemon with available messaging adapters."""
    cfg = settings or get_settings()
    daemon = GatewayDaemon(settings=cfg, engine=build_engine(settings=cfg))

    # Register Telegram Adapter if configured or token in environment
    if cfg.gateway.platforms.telegram.enabled or os.getenv("TELEGRAM_BOT_TOKEN"):
        try:
            from makima.gateway.adapters.telegram import TelegramAdapter
            daemon.register_adapter("telegram", TelegramAdapter(security_manager=daemon.security, engine=daemon.engine))
        except Exception as exc:
            logger.warning(f"Could not register Telegram adapter: {exc}")

    # Register Discord Adapter if configured or token in environment
    if cfg.gateway.platforms.discord.enabled or os.getenv("DISCORD_BOT_TOKEN"):
        try:
            from makima.gateway.adapters.discord import DiscordAdapter
            daemon.register_adapter("discord", DiscordAdapter(security_manager=daemon.security, engine=daemon.engine))
        except Exception as exc:
            logger.warning(f"Could not register Discord adapter: {exc}")

    # Register WhatsApp Adapter if configured
    if cfg.gateway.platforms.whatsapp.enabled:
        try:
            from makima.gateway.adapters.whatsapp import WhatsAppAdapter
            daemon.register_adapter("whatsapp", WhatsAppAdapter(security_manager=daemon.security, engine=daemon.engine))
        except Exception as exc:
            logger.warning(f"Could not register WhatsApp adapter: {exc}")

    # Email is environment-configured rather than represented by a platform
    # token. Register it when credentials are present or explicitly enabled.
    if os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASSWORD"):
        try:
            from makima.gateway.adapters.email_daemon import EmailAdapter
            daemon.register_adapter(
                "email",
                EmailAdapter(security_manager=daemon.security, engine=daemon.engine),
            )
        except Exception as exc:
            logger.warning(f"Could not register Email adapter: {exc}")

    return daemon


def gateway_run_command(
    args: Any,
    console: Console,
    daemon: Optional[GatewayDaemon] = None,
) -> int:
    """Executes 'gateway run' subcommand."""
    d = daemon or setup_gateway_daemon(
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
    )

    active_adapters = list(d.adapters.keys())
    adapters_display = ", ".join(active_adapters) if active_adapters else "None (Local Scheduler & Pairing only)"

    console.print(
        Panel(
            f"[bold green]Starting Makima Gateway Daemon[/bold green]\n\n"
            f"[bold cyan]Active Adapters:[/bold cyan] {adapters_display}\n"
            f"[bold cyan]Security Pairing Code:[/bold cyan] {'Enabled' if d.security.pairing_code_enabled else 'Disabled'}\n"
            f"[bold cyan]Allow All Users:[/bold cyan] {'Yes' if d.security.allow_all_users else 'No (Restricted to allowlist/pairing)'}\n\n"
            f"[dim]Press [bold yellow]Ctrl+C[/bold yellow] to stop the daemon gracefully.[/dim]",
            title="[bold cyan]Makima Gateway Supervisor[/bold cyan]",
            box=box.ROUNDED,
            border_style="green",
        )
    )

    try:
        asyncio.run(d.run_forever())
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Gateway daemon stopped cleanly by user.[/yellow]")
    except Exception as exc:
        console.print(f"\n[bold red]Gateway daemon encountered error:[/bold red] {exc}")
        return 1

    return 0


# -----------------------------------------------------------------------------
# 4. Interactive Chat REPL & Single-Prompt Execution
# -----------------------------------------------------------------------------

def print_repl_help(console: Console) -> None:
    """Prints help for REPL commands."""
    help_table = Table(
        title="[bold cyan]Makima REPL Commands[/bold cyan]",
        box=box.SIMPLE,
        header_style="bold magenta",
    )
    help_table.add_column("Command", style="bold yellow")
    help_table.add_column("Description", style="white")

    help_table.add_row(":quit, :exit, :q", "Exit the chat session.")
    help_table.add_row(":clear", "Clear the terminal screen.")
    help_table.add_row(":tools", "List all registered tools.")
    help_table.add_row(":status", "Show system diagnostics and provider status.")
    help_table.add_row(":reset, :new", "Clear current session conversation history.")
    help_table.add_row(":help, :?", "Display this help menu.")

    console.print(help_table)


async def execute_agent_turn(
    prompt: str,
    engine: HermesAgentEngine,
    registry: ToolRegistry,
    conversation_history: List[Message],
    task: str,
    console: Console,
    use_markdown: bool = True,
    max_turns: Optional[int] = None,
) -> bool:
    """
    Executes a single turn of the HermesAgentEngine, dynamically updating a Rich spinner
    as tool calls are executed, and prints the result in a styled panel.
    Returns True if turn succeeded, False otherwise.
    """
    with console.status("[bold cyan]Makima is thinking...[/bold cyan]", spinner="dots") as status_spinner:

        def on_turn_end(turn: int, response: ProviderResponse) -> None:
            if response.tool_calls:
                call_names = ", ".join(f"[cyan]{escape(c.name)}[/cyan]" for c in response.tool_calls)
                status_spinner.update(
                    f"[bold yellow]Executing tool ({turn}):[/bold yellow] {call_names}..."
                )

        try:
            result = await engine.run(
                prompt=prompt,
                messages=conversation_history if conversation_history else None,
                tools=registry,
                task=task,
                max_turns=max_turns,
                on_turn_end=on_turn_end,
            )

            # Update working messages history
            conversation_history.clear()
            conversation_history.extend(result.messages)

            # Render output
            header = f"[bold cyan]Makima[/bold cyan] [dim]({result.model_used or 'assistant'} | {result.latency_ms:.0f}ms | {result.turn_count} turn{'s' if result.turn_count != 1 else ''})[/dim]"

            if result.error and not result.completed:
                console.print(
                    Panel(
                        f"[yellow]{escape(result.content)}[/yellow]",
                        title="[bold yellow]Agent Notice[/bold yellow]",
                        box=box.ROUNDED,
                        border_style="yellow",
                    )
                )
            else:
                if use_markdown:
                    console.print(
                        Panel(
                            Markdown(result.content),
                            title=header,
                            box=box.ROUNDED,
                            border_style="cyan",
                        )
                    )
                else:
                    console.print(
                        Panel(
                            result.content,
                            title=header,
                            box=box.ROUNDED,
                            border_style="cyan",
                        )
                    )
            return True

        except Exception as exc:
            logger.error(f"Error during agent turn: {exc}", exc_info=True)
            console.print(
                Panel(
                    f"[bold red]Execution Error:[/bold red] {escape(str(exc))}\n\n"
                    f"[dim]Tip: Check 'makima status' to ensure API credentials or Ollama are active.[/dim]",
                    title="[bold red]Agent Turn Failed[/bold red]",
                    box=box.ROUNDED,
                    border_style="red",
                )
            )
            return False


def chat_command(
    args: Any,
    console: Console,
    engine: Optional[HermesAgentEngine] = None,
    registry: Optional[ToolRegistry] = None,
    prompt_fn: Optional[Callable[[str], str]] = None,
) -> int:
    """Executes 'chat' subcommand: single-turn message or interactive REPL."""
    active_engine = engine or build_engine()
    active_registry = registry or build_registry()
    task = getattr(args, "task", "fast_chat") or "fast_chat"
    use_markdown = not getattr(args, "no_markdown", False)
    single_message = getattr(args, "message", None)
    max_turns = getattr(args, "max_turns", None)

    # 1. Single message mode (non-interactive)
    if single_message:
        success = asyncio.run(
            execute_agent_turn(
                prompt=single_message,
                engine=active_engine,
                registry=active_registry,
                conversation_history=[],
                task=task,
                console=console,
                use_markdown=use_markdown,
                max_turns=max_turns,
            )
        )
        return 0 if success else 1

    # 2. Interactive REPL session
    console.print(
        Panel.fit(
            "[bold cyan]Makima v2[/bold cyan] — Autonomous Desktop AI Assistant\n"
            "[dim]Commands: [bold]:tools[/bold] (list tools) | [bold]:status[/bold] (diagnostics) | "
            "[bold]:clear[/bold] (clear) | [bold]:reset[/bold] (new topic) | [bold]:quit[/bold] (exit)[/dim]",
            title="[bold magenta]Interactive Chat REPL[/bold magenta]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    conversation_history: List[Message] = []

    while True:
        try:
            if prompt_fn:
                user_input = prompt_fn("[bold magenta]Makima[/bold magenta] > ")
            else:
                user_input = Prompt.ask("[bold magenta]Makima[/bold magenta] > ", console=console)

            if user_input is None:
                break

            user_input = user_input.strip()

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session closed.[/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        # REPL Escape Commands
        if cmd in (":quit", ":exit", ":q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == ":clear":
            console.clear()
            continue

        if cmd == ":tools":
            render_tools_table(active_registry.list_tools(), console=console)
            continue

        if cmd == ":status":
            render_status_dashboard(console=console)
            continue

        if cmd in (":reset", ":new"):
            conversation_history.clear()
            console.print("[dim]Conversation history reset.[/dim]")
            continue

        if cmd in (":help", ":?"):
            print_repl_help(console=console)
            continue

        # Execute agent turn
        asyncio.run(
            execute_agent_turn(
                prompt=user_input,
                engine=active_engine,
                registry=active_registry,
                conversation_history=conversation_history,
                task=task,
                console=console,
                use_markdown=use_markdown,
                max_turns=max_turns,
            )
        )

    return 0


# -----------------------------------------------------------------------------
# 5. CLI Parser & Main Entrypoint
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Builds the primary argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="makima",
        description="Makima v2 — Autonomous Desktop AI Assistant CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # chat subcommand
    chat_p = subparsers.add_parser("chat", help="Start an interactive chat REPL or send a single prompt")
    chat_p.add_argument("--task", "-t", default="fast_chat", help="ParetoRouter task cascade (default: fast_chat)")
    chat_p.add_argument("--message", "-m", "--prompt", "-p", dest="message", default=None, help="Execute a single query and exit")
    chat_p.add_argument("--max-turns", type=int, default=30, help="Maximum autonomous turns allowed (default: 30)")
    chat_p.add_argument("--no-markdown", action="store_true", help="Disable rich markdown formatting")

    # tools subcommand
    tools_p = subparsers.add_parser("tools", help="Inspect and manage Makima tool registry")
    tools_sub = tools_p.add_subparsers(dest="tools_action", help="Tools action")
    tools_list_p = tools_sub.add_parser("list", help="List registered tools")
    tools_list_p.add_argument("--tag", "-t", default=None, help="Filter tools by tag")

    # gateway subcommand
    gateway_p = subparsers.add_parser("gateway", help="Multi-platform messaging gateway daemon")
    gateway_sub = gateway_p.add_subparsers(dest="gateway_action", help="Gateway action")
    gateway_run_p = gateway_sub.add_parser("run", help="Start the gateway daemon supervisor")
    gateway_run_p.add_argument("--host", default=None, help="Host address for gateway server")
    gateway_run_p.add_argument("--port", type=int, default=None, help="Port for gateway server")

    # status subcommand
    subparsers.add_parser("status", help="Display system diagnostics, providers, and memory state")

    # overlay subcommand
    subparsers.add_parser("overlay", help="Launch the native Windows Spotlight HUD overlay")

    return parser


def cli_main(
    args: Optional[List[str]] = None,
    console: Optional[Console] = None,
    engine: Optional[HermesAgentEngine] = None,
    registry: Optional[ToolRegistry] = None,
    prompt_fn: Optional[Callable[[str], str]] = None,
    daemon: Optional[GatewayDaemon] = None,
) -> int:
    """
    Main CLI entrypoint for Makima v2.
    
    Args:
        args: Optional list of CLI arguments (defaults to sys.argv[1:]).
        console: Optional Rich Console instance for output.
        engine: Optional HermesAgentEngine instance (for testing/mocking).
        registry: Optional ToolRegistry instance (for testing/mocking).
        prompt_fn: Optional input prompt callback (for testing/mocking).
        daemon: Optional GatewayDaemon instance (for testing/mocking).
    
    Returns:
        Exit code (0 for success, non-zero for error).
    """
    _safe_reconfigure_streams()

    con = console or Console()
    parser = build_parser()

    effective_args = args if args is not None else sys.argv[1:]

    # If no arguments provided, display help and return 0
    if not effective_args:
        parser.print_help()
        return 0

    parsed = parser.parse_args(effective_args)

    if parsed.subcommand == "chat":
        return chat_command(
            parsed,
            console=con,
            engine=engine,
            registry=registry,
            prompt_fn=prompt_fn,
        )

    if parsed.subcommand == "tools":
        if getattr(parsed, "tools_action", None) == "list" or not getattr(parsed, "tools_action", None):
            return tools_list_command(parsed, console=con, registry=registry)
        con.print(f"[yellow]Unknown tools action: {escape(str(parsed.tools_action))}[/yellow]")
        return 1

    if parsed.subcommand == "gateway":
        if getattr(parsed, "gateway_action", None) == "run":
            return gateway_run_command(parsed, console=con, daemon=daemon)
        con.print(f"[yellow]Unknown gateway action: {escape(str(parsed.gateway_action))}[/yellow]")
        return 1

    if parsed.subcommand == "status":
        return status_command(parsed, console=con)

    if parsed.subcommand == "overlay":
        from makima.overlay.hud import launch_overlay
        con.print("[bold magenta]👑 Launching Makima Spotlight HUD Overlay...[/bold magenta]")
        con.print("[dim]Press [Ctrl+Space] to toggle, [Esc] to dismiss.[/dim]")
        hud = launch_overlay(engine=engine)
        hud.mainloop()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(cli_main())
