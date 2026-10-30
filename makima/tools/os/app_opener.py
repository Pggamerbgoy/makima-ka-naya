"""
Makima v2 — Instant Windows Application Controller via AppOpener.
Architectural Pattern: Clean, modular, library-first application lifecycle management.
Features:
- AppOpener integration for launching and closing Windows Store & Win32 applications.
- Fuzzy matching & closest-match heuristics.
- Zero-cost fallback to os.startfile for registered URI protocols (e.g. 'calc:', 'spotify:', 'ms-settings:').
- Dry-run capability for testing and safe inspection.
"""

from __future__ import annotations

import contextlib
import difflib
import io
import logging
import os
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Union

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _get_appopener() -> Any:
    """Load AppOpener only when an application tool is actually called.

    AppOpener updates its catalog during import. Eager importing therefore
    makes merely discovering Makima tools write into site-packages and can
    break read-only benchmark/CI environments.
    """
    try:
        import AppOpener
    except ImportError as exc:
        raise RuntimeError("AppOpener is unavailable on this runtime.") from exc
    return AppOpener


def get_installed_applications() -> List[str]:
    """
    Retrieve the sorted list of application names registered in AppOpener's catalog.

    Returns:
        List of application names (lowercase strings).
    """
    try:
        app_names = list(_get_appopener().give_appnames(upper=False))
        return sorted(app_names)
    except Exception as exc:
        logger.warning("Failed to retrieve AppOpener application list: %s", exc)
        return []


def _resolve_application_target(app_name: str, match_closest: bool = True) -> Optional[str]:
    """
    Internal helper to resolve an application name against AppOpener's catalog,
    special aliases, or close matches.
    """
    clean_lower = app_name.strip().lower()

    # Direct alias resolution (e.g. 'calc' -> 'calculator')
    if clean_lower == "calc":
        return "calculator"

    # Known registered AppOpener applications
    known_apps = get_installed_applications()
    if clean_lower in known_apps:
        return clean_lower

    # Closest match if requested
    if match_closest and known_apps:
        matches = difflib.get_close_matches(clean_lower, known_apps, n=1, cutoff=0.6)
        if matches:
            return matches[0]

    return None


@tool(
    name="launch_application",
    description="Launch a desktop application or registered URI protocol.",
    tags=["os", "apps", "execution"],
    purpose="Start a named desktop application or registered URI protocol.",
    capabilities=[
        "Resolve and launch an application by name.",
        "Resolve a registered protocol URI and open its associated application.",
        "Perform a dry-run resolution without launching the target.",
    ],
    use_when=[
        "The intended target is a desktop application that should be opened or launched.",
    ],
    avoid_when=[
        "The user intends to close an application that is already running.",
        "The user intends only to change playback state or interact with a website.",
    ],
    examples=[
        "Open the calculator application.",
        "Launch a named desktop application.",
    ],
    side_effect="Launches an application or opens a registered protocol.",
)
def launch_application(
    app_name: str,
    args: Optional[Union[List[str], str]] = None,
    match_closest: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Launch an application by name or registered protocol safely.

    Args:
        app_name: Name of the application (e.g. 'notepad', 'calc', 'spotify') or protocol URI (e.g. 'calc:', 'spotify:', 'ms-settings:').
        args: Optional command line arguments when launching executables.
        match_closest: If True, attempts fuzzy matching when exact name is not registered.
        dry_run: If True, validates resolution without executing the application.

    Returns:
        Dictionary with status, resolved target, method, and message.
    """
    if not app_name or not app_name.strip():
        return {
            "success": False,
            "error": "The 'app_name' parameter cannot be empty.",
        }

    clean_app = app_name.strip()
    candidate = clean_app.rstrip(":")

    # 0. Handle explicit arguments if provided
    if args is not None:
        parsed_args: List[str] = []
        if isinstance(args, str):
            if args.strip():
                parsed_args = shlex.split(args.strip(), posix=False)
        elif isinstance(args, (list, tuple)):
            parsed_args = [str(a) for a in args]

        which_exe = shutil.which(candidate) or shutil.which(f"{candidate}.exe") or candidate
        cmd = [which_exe] + parsed_args
        if dry_run:
            return {
                "success": True,
                "app_name": clean_app,
                "target": which_exe,
                "command": cmd,
                "method": "subprocess",
                "dry_run": True,
                "message": f"Command '{cmd}' is valid and ready to launch (dry-run).",
            }
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
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
                "executable": which_exe,
                "command": cmd,
                "message": f"Successfully launched '{clean_app}' (PID: {proc.pid}).",
            }
        except Exception as proc_exc:
            return {
                "success": False,
                "app_name": clean_app,
                "error": f"Failed to launch with arguments: {proc_exc}",
            }

    is_protocol = ":" in clean_app or clean_app.startswith("ms-")

    # 1. Handle Protocol URIs directly via os.startfile
    if is_protocol:
        if dry_run:
            return {
                "success": True,
                "app_name": clean_app,
                "target": clean_app,
                "method": "protocol",
                "dry_run": True,
                "message": f"Protocol URI '{clean_app}' is valid and ready to launch (dry-run).",
            }

        try:
            os.startfile(clean_app)
            return {
                "success": True,
                "app_name": clean_app,
                "target": clean_app,
                "method": "os.startfile",
                "message": f"Successfully launched protocol URI '{clean_app}' via os.startfile.",
            }
        except Exception as proto_exc:
            logger.debug("Direct os.startfile failed for protocol '%s': %s", clean_app, proto_exc)
            # Fall through to attempt AppOpener after stripping protocol colon

    # 2. Resolve App Target
    candidate = clean_app.rstrip(":")
    resolved_target = _resolve_application_target(candidate, match_closest=match_closest)

    if dry_run:
        if resolved_target:
            return {
                "success": True,
                "app_name": clean_app,
                "target": resolved_target,
                "method": "AppOpener",
                "dry_run": True,
                "message": f"Application '{clean_app}' resolved to '{resolved_target}' (dry-run).",
            }
        # Check PATH fallback in dry-run
        which_path = shutil.which(candidate) or shutil.which(f"{candidate}.exe")
        if which_path:
            return {
                "success": True,
                "app_name": clean_app,
                "target": which_path,
                "method": "path_executable",
                "dry_run": True,
                "message": f"Application '{clean_app}' located on PATH at '{which_path}' (dry-run).",
            }

        return {
            "success": False,
            "app_name": clean_app,
            "dry_run": True,
            "error": f"Application '{clean_app}' could not be resolved in AppOpener or system PATH.",
        }

    # 3. Launch via AppOpener
    target_to_open = resolved_target or candidate
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    appopener_error: Optional[Exception] = None

    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            _get_appopener().open(
                target_to_open,
                output=True,
                match_closest=match_closest,
                throw_error=True,
            )

        out_text = captured_stdout.getvalue()
        # Verify AppOpener actually initiated the launch
        if "OPENING " in out_text:
            return {
                "success": True,
                "app_name": clean_app,
                "target": target_to_open,
                "method": "AppOpener",
                "message": f"Successfully launched '{clean_app}' (resolved to '{target_to_open}') via AppOpener.",
            }

        if not match_closest and "Closest match to " in out_text:
            raise RuntimeError(f"Exact match for '{clean_app}' not found (fuzzy match disabled).")

    except Exception as exc:
        appopener_error = exc
        logger.debug("AppOpener.open failed for '%s': %s", target_to_open, exc)

    # 4. Fallback: os.startfile for registered protocols or executables
    fallback_attempts = [
        f"{candidate}:",      # Registered Windows protocol (e.g. calc:, spotify:)
        candidate,            # System executable or registered shell verb
        f"{candidate}.exe",   # Direct executable
    ]

    for fb in fallback_attempts:
        try:
            os.startfile(fb)
            return {
                "success": True,
                "app_name": clean_app,
                "target": fb,
                "method": "os.startfile_fallback",
                "message": f"Successfully launched '{clean_app}' via os.startfile fallback ('{fb}').",
            }
        except Exception as fb_exc:
            logger.debug("os.startfile fallback failed for '%s': %s", fb, fb_exc)

    # All resolution strategies exhausted
    err_msg = str(appopener_error) if appopener_error else f"Application '{clean_app}' not found."
    return {
        "success": False,
        "app_name": clean_app,
        "error": f"Failed to launch application '{clean_app}': {err_msg}",
    }


@tool(
    name="terminate_application",
    description="Close a running desktop application by application name.",
    tags=["os", "apps", "control"],
    purpose="Request closure of a named application rather than modifying media playback.",
    capabilities=[
        "Find a running application by its user-visible name and request that it close.",
        "Report whether the target application was found and whether closure was accepted.",
    ],
    use_when=[
        "The requested target is a desktop application the user wants to close or exit.",
        "The user wants an application closed while another independent activity should continue.",
    ],
    avoid_when=[
        "The user asks only to pause, stop, or resume audio/video playback.",
        "The user asks to close a browser tab or navigate away from a web page but keep the browser open.",
        "The user asks to shut down or reboot the whole operating system.",
    ],
    examples=[
        "Close a named desktop application.",
        "Close one application while leaving other running applications untouched.",
    ],
    side_effect="Requests application closure; unsaved work in the target application may be affected.",
)
def terminate_application(
    app_name: str,
    match_closest: bool = True,
) -> Dict[str, Any]:
    """
    Terminate a running application by name safely.

    Args:
        app_name: Name of the application to close (e.g. 'notepad', 'calculator', 'calc').
        match_closest: If True, uses fuzzy matching to identify the running process.

    Returns:
        Dictionary reporting termination status and outcome message.
    """
    if not app_name or not app_name.strip():
        return {
            "success": False,
            "error": "The 'app_name' parameter cannot be empty.",
        }

    clean_app = app_name.strip()
    candidate = clean_app.rstrip(":").lower()

    # Alias handling for close
    if candidate == "calc":
        candidate = "calculator"

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()

    try:
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            _get_appopener().close(
                candidate,
                output=True,
                match_closest=match_closest,
                throw_error=True,
            )

        out_text = captured_stdout.getvalue()
        if "is not running" in out_text:
            return {
                "success": False,
                "app_name": clean_app,
                "error": f"Application '{clean_app}' is not currently running.",
            }

        return {
            "success": True,
            "app_name": clean_app,
            "message": f"Successfully terminated application '{clean_app}'.",
        }

    except Exception as exc:
        logger.debug("AppOpener.close failed for '%s': %s", clean_app, exc)
        return {
            "success": False,
            "app_name": clean_app,
            "error": f"Failed to terminate application '{clean_app}': {exc}",
        }
