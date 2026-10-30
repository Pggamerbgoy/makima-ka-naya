"""
Makima v2 — Spotlight HUD Overlay CLI Launcher.
Run with: python -m makima.overlay.main

Features:
1. Native GPU Hardware-Accelerated Slint Overlay (makima-native-overlay.exe)
   - Real Skia/FemtoVG GPU acceleration, true transparent glass, 0% blur
2. High-DPI Pure Python Windows Native HUD (SpotlightHUD)
   - Per-monitor DPI awareness, Win32 DWM acrylic blur, DwmExtendFrame drop shadows
"""

from __future__ import annotations

import logging
import pathlib
import subprocess
import sys

from makima.overlay.hud import SpotlightHUD


def _assign_process_to_kill_on_close_job(proc: subprocess.Popen) -> Any:
    """
    Attaches child process to a Windows Job Object configured with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. If the parent Python process terminates
    or crashes, Windows automatically terminates the native overlay binary immediately,
    preventing orphaned zombie processes and GDI handle leaks.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None

        handle = getattr(proc, "_handle", None)
        if handle:
            kernel32.AssignProcessToJobObject(job, handle)

        return job
    except Exception as e:
        logging.getLogger("makima.overlay").debug(f"Could not assign process to Job Object: {e}")
        return None


def _safe_reconfigure_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    _safe_reconfigure_streams()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 70)
    print("[MAKIMA v2] — SPOTLIGHT HUD OVERLAY INITIALIZED")
    print("• Press [Ctrl + Space] anywhere on Windows to toggle the HUD.")
    print("• Press [Esc] to dismiss or hide the HUD.")
    print("• Click and drag the top title area to reposition.")
    print("=" * 70)

    # Check for compiled Rust Slint overlay binary
    bin_path = pathlib.Path(__file__).parent / "bin" / "makima-native-overlay.exe"
    exe_target = bin_path if bin_path.exists() else None

    # Priority 1: Slint GPU native binary if available
    if "--python" not in sys.argv and exe_target is not None:
        print(f"[+] Launching Hardware-Accelerated Slint GPU Overlay: {exe_target}")
        proc = subprocess.Popen([str(exe_target)])
        job_handle = _assign_process_to_kill_on_close_job(proc)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return 0

    # Priority 2: Modern WebView2 / Web Spotlight HUD (Option 1)
    if "--tkinter" not in sys.argv:
        try:
            from makima.overlay.hud_webview import WebViewSpotlightHUD
            print("[+] Launching GPU-Accelerated WebView2 Spotlight HUD...")
            web_hud = WebViewSpotlightHUD()
            if web_hud.launch():
                return 0
        except Exception as exc:
            logging.getLogger("makima.overlay").debug(f"WebView2 HUD launch skipped: {exc}")

    # Priority 3: High-DPI Windows Tkinter Native HUD Fallback
    print("[+] Launching Windows Native Tkinter HUD (Fallback)...")
    hud = SpotlightHUD()
    hud.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

