"""
Makima v2 — Native Desktop App Launcher.
Starts the FastAPI backend in a daemon thread and launches a standalone,
borderless/native desktop window using Microsoft Edge App Mode or PyWebView.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

logger = logging.getLogger("makima.desktop")


def _safe_reconfigure_streams() -> None:
    """Configures stdout and stderr to handle UTF-8 cleanly across Windows terminals."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _is_port_in_use(host: str, port: int) -> bool:
    """Checks if a local network port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_for_server(host: str, port: int, timeout: float = 25.0) -> bool:
    """Polls until the backend server is accepting connections."""
    start = time.monotonic()
    print("[*] Starting Makima backend server (loading plugins & providers)...", end="", flush=True)
    while time.monotonic() - start < timeout:
        if _is_port_in_use(host, port):
            print(" [OK] Ready!\n")
            return True
        print(".", end="", flush=True)
        time.sleep(0.4)
    print(" [ERROR] Timeout!\n")
    return False


def _find_browser_app_executable() -> Optional[Path]:
    """Finds a Chromium-based executable (Edge or Chrome) for standalone frameless app mode."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _find_edge_executable() -> Optional[Path]:
    """Deprecated alias for _find_browser_app_executable."""
    return _find_browser_app_executable()


def run_desktop(host: str = "127.0.0.1", port: int = 8000, debug: bool = False) -> int:
    """
    Launches Makima v2 as a native Windows desktop app.
    1. Spawns the Makima FastAPI backend as an isolated background subprocess.
    2. Opens the chat UI in a standalone native desktop window.
    3. Blocks cleanly until the window is dismissed.
    """
    _safe_reconfigure_streams()
    print("=" * 70)
    print("[MAKIMA v2] — NATIVE DESKTOP APPLICATION")
    print(f"• Backend URL: http://{host}:{port}")
    print("• Desktop UI: Standalone Native Window")
    print("• Press [Ctrl + C] in this console to shut down.")
    print("=" * 70)

    # 1. Start backend server if not already running
    backend_proc: Optional[subprocess.Popen] = None
    if not _is_port_in_use(host, port):
        # Ensure all environment variables from project and user .env are loaded
        try:
            import dotenv
            for env_candidate in [
                Path.cwd() / ".env",
                Path(__file__).resolve().parents[2] / ".env",
                Path.home() / ".makima" / ".env",
            ]:
                if env_candidate.exists():
                    dotenv.load_dotenv(str(env_candidate), override=False)
        except Exception:
            pass

        backend_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "makima.api.app:create_app",
            "--factory",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "info" if debug else "warning",
        ]
        sub_env = dict(os.environ)
        sub_env["PYTHONIOENCODING"] = "utf-8"
        backend_proc = subprocess.Popen(backend_cmd, env=sub_env)

        # Attach Win32 Job Object so backend dies automatically if this launcher terminates
        try:
            from makima.overlay.main import _assign_process_to_kill_on_close_job
            _assign_process_to_kill_on_close_job(backend_proc)
        except Exception:
            pass

        if not _wait_for_server(host, port, timeout=25.0):
            print(f"[!] Error: Makima backend failed to start on http://{host}:{port} within 25 seconds.")
            if backend_proc and backend_proc.poll() is not None:
                print(f"Backend process exited early with code {backend_proc.returncode}.")
            if backend_proc:
                backend_proc.terminate()
            return 1
    else:
        print(f"[i] Connected to existing active Makima instance on port {port}.\n")

    ui_url = f"http://{host}:{port}"

    try:
        # 2. Check for PyWebView
        try:
            import webview
            print("[+] Launching via PyWebView native desktop window...")
            webview.create_window(
                title="Makima v2",
                url=ui_url,
                width=1280,
                height=850,
                min_size=(800, 600),
                background_color="#090d16",
            )
            webview.start()
            return 0
        except ImportError:
            pass

        # 3. Native Standalone App Window (Chromium / Edge / Chrome App Mode with isolated profile)
        browser_exe = _find_browser_app_executable()
        if browser_exe:
            profile_dir = Path.home() / ".makima" / "desktop_profile"
            try:
                from makima.config import get_settings
                profile_dir = get_settings().state_dir_path / "desktop_profile"
            except Exception:
                pass
            profile_dir.mkdir(parents=True, exist_ok=True)

            print(f"[+] Launching Native Standalone Desktop Window: {ui_url}")
            app_args = [
                str(browser_exe),
                f"--app={ui_url}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1280,850",
            ]
            proc = subprocess.Popen(app_args)
            try:
                from makima.overlay.main import _assign_process_to_kill_on_close_job
                _assign_process_to_kill_on_close_job(proc)
            except Exception:
                pass
            try:
                return proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                return 0

        # 4. Fallback to standard system browser
        print("[+] Launching Makima in default system browser...")
        webbrowser.open(ui_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[+] Makima desktop session closed.")
            return 0
    finally:
        if backend_proc and backend_proc.poll() is None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=2.0)
            except Exception:
                backend_proc.kill()
