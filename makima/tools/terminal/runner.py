"""
Makima v2 — Sandboxed Terminal Runner.
Architectural Pattern: Async Subprocess Execution with Safety Interception and Resource Clamping.
Zero-Hardcoding Guarantee: Dynamic workspace resolution, environment probing, and strict guardrails.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from makima.config import get_settings
from makima.core.guardrails import Guardrails
from makima.tools.registry import ToolExecutionError, tool

logger = logging.getLogger("makima.tools.terminal.runner")


# Maximum output size allowed before truncation (100 KB)
MAX_OUTPUT_BYTES: int = 100 * 1024


class CommandTimeoutError(ToolExecutionError, TimeoutError):
    """Raised when command execution exceeds the configured timeout threshold."""

    def __init__(self, command: str, timeout_seconds: float) -> None:
        super().__init__(f"Command '{command}' timed out after {timeout_seconds} seconds.")
        self.command = command
        self.timeout_seconds = timeout_seconds


def get_workspace_dir(custom_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Dynamically resolves and ensures the sandbox workspace directory.
    Falls back to ~/.makima/workspace if settings are unavailable.
    """
    if custom_path is not None:
        ws = Path(custom_path).expanduser().resolve()
    else:
        try:
            settings = get_settings()
            ws = settings.workspace_dir_path.resolve()
        except Exception:
            ws = (Path.home() / ".makima" / "workspace").resolve()

    ws.mkdir(parents=True, exist_ok=True)
    return ws


def clamp_to_workspace(
    cwd: Optional[Union[str, Path]] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Clamps the target working directory strictly within the designated workspace.
    Guarantees no directory traversal or path escapes outside the designated workspace.

    Args:
        cwd: Requested working directory (relative or absolute).
        workspace_dir: Optional workspace root directory.

    Returns:
        A resolved Path guaranteed to be within the workspace.
    """
    ws = get_workspace_dir(custom_path=workspace_dir)

    if not cwd:
        return ws

    target = Path(cwd).expanduser()
    if not target.is_absolute():
        target = (ws / target).resolve()
    else:
        target = target.resolve()

    # Verify target is equal to or a subpath of workspace
    try:
        target.relative_to(ws)
        target.mkdir(parents=True, exist_ok=True)
        return target
    except ValueError:
        # Fallback check for case-insensitive filesystems (Windows)
        try:
            target_str = str(target).lower().replace("/", "\\")
            ws_str = str(ws).lower().replace("/", "\\")
            if target_str == ws_str or target_str.startswith(ws_str + "\\"):
                target.mkdir(parents=True, exist_ok=True)
                return target
        except Exception:
            pass

        logger.warning(
            "Directory traversal/escape detected: requested cwd '%s' resolved to '%s' "
            "outside workspace '%s'. Clamping to workspace root.",
            cwd,
            target,
            ws,
        )
        return ws


def truncate_output(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> Tuple[str, bool]:
    """
    Safely truncates output text if its UTF-8 byte representation exceeds max_bytes.

    Returns:
        (truncated_text, was_truncated: bool)
    """
    if not text:
        return "", False

    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False

    # Slice at byte boundary and decode safely
    truncated_bytes = encoded[:max_bytes]
    truncated_text = truncated_bytes.decode("utf-8", errors="ignore")
    suffix = f"\n... [Output truncated: exceeded {max_bytes // 1024}KB limit]"
    return truncated_text + suffix, True


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """
    Safely terminates or kills the subprocess and all descendant child processes.
    On Windows, uses 'taskkill /F /T /PID' to guarantee no orphan child processes survive.
    """
    if proc.returncode is not None:
        return

    pid = proc.pid
    if sys.platform == "win32":
        try:
            kill_proc = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill_proc.wait()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception:
            pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=1.5)
    except Exception:
        pass


SHELL_BUILTINS: set[str] = {
    "dir", "echo", "type", "cls", "cd", "copy", "del", "move",
    "mkdir", "md", "rmdir", "rd", "ren", "rename", "set", "path",
    "ver", "vol", "color",
}


def resolve_command_args(command: str) -> Tuple[str, List[str]]:
    """
    Intelligently maps a command string into executable binary and arguments
    for safe invocation via asyncio.create_subprocess_exec (Rule 7).
    Dispatches Windows built-in commands (echo, dir, etc.) and pipeline expressions
    to cmd.exe /c, and standalone executables (python, git, etc.) directly.
    """
    import shutil

    cmd_clean = command.strip()
    try:
        parts = shlex.split(cmd_clean, posix=(sys.platform != "win32"))
    except Exception:
        parts = cmd_clean.split()

    if not parts:
        cmd_bin = os.environ.get("COMSPEC", "cmd.exe") if sys.platform == "win32" else "/bin/sh"
        return cmd_bin, []

    first_token = parts[0].lower()
    has_shell_operators = any(ch in cmd_clean for ch in ("|", ">", "<", "&", "^" if sys.platform == "win32" else ";"))

    # Resolve python/python3 directly to the running Python interpreter to avoid WindowsApps execution alias collisions
    if first_token in ("python", "python3", "python.exe"):
        return sys.executable, parts[1:]

    if sys.platform == "win32":
        if (
            first_token in SHELL_BUILTINS
            or has_shell_operators
            or shutil.which(parts[0]) is None
        ):
            cmd_bin = os.environ.get("COMSPEC", "cmd.exe")
            return cmd_bin, ["/c", cmd_clean]
        else:
            return parts[0], parts[1:]
    else:
        if has_shell_operators or shutil.which(parts[0]) is None:
            shell_bin = os.environ.get("SHELL", "/bin/sh")
            return shell_bin, ["-c", cmd_clean]
        else:
            return parts[0], parts[1:]


def _try_windows_shell_start(command: str, cwd: Path) -> Optional[Dict[str, Any]]:
    """
    Intercepts Windows 'start' commands to launch GUI programs/URLs visibly
    via ShellExecuteW (SW_SHOWNORMAL = 1), preventing child processes from inheriting
    hidden window (SW_HIDE) state from background server daemons.
    """
    if sys.platform != "win32":
        return None

    cmd_clean = command.strip()
    if not (cmd_clean.lower() == "start" or cmd_clean.lower().startswith("start ")):
        return None

    try:
        parts = shlex.split(cmd_clean, posix=False)
    except Exception:
        parts = cmd_clean.split()

    if not parts or parts[0].lower() != "start":
        return None

    tokens = parts[1:]
    if not tokens:
        return None

    flags: List[str] = []
    rest: List[str] = []
    for tok in tokens:
        if tok.startswith("/") and len(tok) >= 2:
            flags.append(tok.lower())
        else:
            rest.append(tok)

    if not rest:
        return None

    # In Windows cmd: start ["title"] [program/url] [parameters]
    if rest[0] in ('""', "''", ""):
        if len(rest) > 1:
            target = rest[1]
            args = rest[2:]
        else:
            return None
    else:
        target = rest[0]
        args = rest[1:]

    target_clean = target.strip('"\'')
    args_str = " ".join(args).strip() if args else None

    # Determine show command (SW_SHOWMAXIMIZED = 3, SW_SHOWMINIMIZED = 2, SW_SHOWNORMAL = 1)
    show_cmd = 1
    if "/max" in flags:
        show_cmd = 3
    elif "/min" in flags:
        show_cmd = 2

    try:
        import ctypes
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            target_clean,
            args_str,
            str(cwd),
            show_cmd,
        )
        if res > 32:
            logger.info("Launched '%s' in visible desktop window (ShellExecute status: %d)", target_clean, res)
            return {
                "command": command,
                "stdout": f"Launched '{target_clean}' in visible desktop window (ShellExecute status: {res}).",
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "cwd": str(cwd),
                "truncated": False,
            }
        else:
            logger.debug("ShellExecuteW returned error code %d for '%s'", res, command)
    except Exception as exc:
        logger.debug("ShellExecuteW dispatch failed for '%s': %s", command, exc)

    return None


@tool(
    name="execute_command",
    description=(
        "Executes a shell command asynchronously in a sandboxed, directory-clamped environment "
        "with strict timeout enforcement, safety guardrail validation, and output truncation."
    ),
    tags=["terminal", "system", "sandbox"],
)
async def execute_command(
    command: str,
    timeout_seconds: int = 45,
    cwd: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Executes a shell command with safety guardrails, timeout, and directory clamping.

    Args:
        command: Shell command or script to execute.
        timeout_seconds: Maximum allowed execution time in seconds (default: 45).
        cwd: Optional working directory (clamped within workspace).

    Keyword Args:
        workspace_dir: Optional custom workspace root for isolation.
        raise_on_timeout: If True, raises CommandTimeoutError instead of returning timed_out status.
        guardrails: Optional custom Guardrails instance.

    Returns:
        Dict containing command, stdout, stderr, exit_code, timed_out, cwd, and truncated status.
    """
    workspace_dir = kwargs.get("workspace_dir")
    raise_on_timeout = bool(kwargs.get("raise_on_timeout", False))
    guardrails = kwargs.get("guardrails")

    if not command or not command.strip():
        effective_ws = get_workspace_dir(custom_path=workspace_dir)
        return {
            "command": command,
            "stdout": "",
            "stderr": "Empty command provided.",
            "exit_code": 1,
            "timed_out": False,
            "cwd": str(effective_ws),
            "truncated": False,
        }

    # 1. Validates command against makima.core.guardrails.Guardrails.validate_command
    active_guardrails = guardrails or Guardrails()
    active_guardrails.validate_command(command)

    # 2. Enforce directory clamping within workspace
    effective_cwd = clamp_to_workspace(cwd=cwd, workspace_dir=workspace_dir)

    # Windows GUI / Start Interception: Ensure visible desktop window via ShellExecuteW
    shell_result = _try_windows_shell_start(command, effective_cwd)
    if shell_result is not None:
        return shell_result

    # 3. Build subprocess invocation using asyncio.create_subprocess_exec (Rule 7)
    exec_bin, exec_args = resolve_command_args(command)
    logger.debug("Executing subprocess: %s %s in %s (timeout: %ss)", exec_bin, exec_args, effective_cwd, timeout_seconds)

    try:
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_args,
            cwd=str(effective_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        logger.error("Failed to spawn subprocess for command '%s': %s", command, exc)
        err_msg = str(exc) or getattr(exc, "strerror", "") or type(exc).__name__
        return {
            "command": command,
            "stdout": "",
            "stderr": (
                f"Subprocess spawn failed ({type(exc).__name__}: {err_msg}). "
                "Diagnostic: This is a local OS execution/path issue, not a sandbox restriction."
            ),
            "exit_code": -1,
            "timed_out": False,
            "cwd": str(effective_cwd),
            "truncated": False,
        }


    # 4. Enforce strict timeout
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(timeout_seconds),
        )
    except asyncio.TimeoutError:
        logger.warning("Command '%s' timed out after %s seconds. Terminating process tree.", command, timeout_seconds)
        await _kill_process_tree(proc)

        if raise_on_timeout:
            raise CommandTimeoutError(command=command, timeout_seconds=float(timeout_seconds))

        return {
            "command": command,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds} seconds.",
            "exit_code": 124,
            "timed_out": True,
            "cwd": str(effective_cwd),
            "truncated": False,
        }

    # 5. Decode output safely with UTF-8 fallback
    stdout_text = stdout_raw.decode("utf-8", errors="replace")
    stderr_text = stderr_raw.decode("utf-8", errors="replace")

    # 6. Apply safe output truncation (max 100KB)
    stdout_trunc, out_truncated = truncate_output(stdout_text, max_bytes=MAX_OUTPUT_BYTES)
    stderr_trunc, err_truncated = truncate_output(stderr_text, max_bytes=MAX_OUTPUT_BYTES)
    was_truncated = out_truncated or err_truncated

    # 7. Redact potential secrets before returning output
    stdout_sanitized = active_guardrails.filter_secrets(stdout_trunc)
    stderr_sanitized = active_guardrails.filter_secrets(stderr_trunc)

    return {
        "command": command,
        "stdout": stdout_sanitized,
        "stderr": stderr_sanitized,
        "exit_code": proc.returncode if proc.returncode is not None else 0,
        "timed_out": False,
        "cwd": str(effective_cwd),
        "truncated": was_truncated,
    }
