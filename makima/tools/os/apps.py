"""
Makima v2 — Application Launching Tools.
Architectural Pattern: Clean, modular, library-first process execution using subprocess.Popen safely.
Zero-Hardcoding Guarantee: Dynamic executable resolution with safe argument handling.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _resolve_executable_path(app_name: str) -> Optional[str]:
    """
    Dynamically locate the application executable on Windows.
    Checks exact path, shutil.which, PATHEXT (.exe, .cmd, .bat), and Windows system folders.
    """
    clean_name = app_name.strip()

    # 1. Direct path check
    direct_path = Path(clean_name)
    if direct_path.is_file():
        return str(direct_path.resolve())

    # 2. PATH resolution via shutil.which
    which_path = shutil.which(clean_name)
    if which_path:
        return which_path

    # Try appending .exe if not present
    if not clean_name.lower().endswith(".exe"):
        which_exe = shutil.which(f"{clean_name}.exe")
        if which_exe:
            return which_exe

    # 3. Known Windows directories fallback
    windir = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidates = [
        Path(windir) / clean_name,
        Path(windir) / f"{clean_name}.exe",
        Path(windir) / "System32" / clean_name,
        Path(windir) / "System32" / f"{clean_name}.exe",
        Path(windir) / "SysWOW64" / clean_name,
        Path(windir) / "SysWOW64" / f"{clean_name}.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    return None


@tool(
    name="launch_app",
    description="Launch an application or executable process safely using subprocess.Popen.",
    tags=["os", "apps", "execution"],
)
def launch_app(
    app_name: str,
    args: Optional[Union[List[str], str]] = None,
) -> Dict[str, Any]:
    """
    Launch a local application or command safely.

    Args:
        app_name: The name or path of the executable to run (e.g. 'notepad', 'calc', 'wt.exe', 'python').
        args: Optional command line arguments. Can be a list of argument strings or a command string.

    Returns:
        Dictionary reporting launch status, PID, command arguments, and outcome message.
    """
    if not app_name or not app_name.strip():
        return {
            "success": False,
            "error": "The 'app_name' parameter cannot be empty.",
        }

    clean_app = app_name.strip()

    # Parse arguments safely without shell injection
    parsed_args: List[str] = []
    if args is not None:
        if isinstance(args, str):
            if args.strip():
                parsed_args = shlex.split(args.strip(), posix=False)
        elif isinstance(args, (list, tuple)):
            parsed_args = [str(a) for a in args]

    # Resolve executable
    resolved_path = _resolve_executable_path(clean_app)
    executable_target = resolved_path or clean_app

    # Construct command list
    cmd = [executable_target] + parsed_args

    # Configure creation flags (Windows: CREATE_NEW_PROCESS_GROUP avoids blocking or killing child on parent signals)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

        return {
            "success": True,
            "pid": proc.pid,
            "app_name": clean_app,
            "executable": executable_target,
            "command": cmd,
            "message": f"Successfully launched '{clean_app}' (PID: {proc.pid}).",
        }
    except FileNotFoundError:
        # Fallback for Windows URI protocols (e.g. ms-settings:, calc:, https:)
        if os.name == "nt" and (":" in clean_app or clean_app.startswith("ms-")):
            try:
                proc = subprocess.Popen(
                    ["explorer.exe", clean_app],
                    creationflags=creationflags,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                return {
                    "success": True,
                    "pid": proc.pid,
                    "app_name": clean_app,
                    "executable": "explorer.exe",
                    "command": ["explorer.exe", clean_app],
                    "message": f"Successfully launched protocol URI '{clean_app}' via shell.",
                }
            except Exception as uri_exc:
                return {
                    "success": False,
                    "app_name": clean_app,
                    "error": f"Failed to launch protocol URI: {uri_exc}",
                }

        return {
            "success": False,
            "app_name": clean_app,
            "error": f"Executable '{clean_app}' not found on system or PATH.",
        }
    except PermissionError as exc:
        return {
            "success": False,
            "app_name": clean_app,
            "error": f"Permission denied executing '{clean_app}': {exc}",
        }
    except Exception as exc:
        logger.exception("Error launching application '%s': %s", clean_app, exc)
        return {
            "success": False,
            "app_name": clean_app,
            "error": f"Failed to launch application: {exc}",
        }
