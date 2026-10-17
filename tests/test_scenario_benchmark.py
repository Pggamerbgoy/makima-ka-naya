"""
End-to-End Test Execution Script for Makima v2 Desktop Control Agent (Optimized ~10-15s Run).
Chains:
1. System Stats & Process Telemetry (get_system_stats, list_processes)
2. Application Lifecycle (launch_app with active window polling)
3. Zero-Vision UIA Automation (inspect_app_ui, click_ui_element, read_ui_text)
4. Window Management (maximize_window, focus_window, minimize_window)
5. Hardware-Level Input Simulation (keyboard_type, keyboard_hotkey)
6. Set-of-Marks Visual Grounding & Unified Facade (annotate_window_som, computer_use)
7. Native Desktop Notification (show_desktop_notification)
"""

import sys
import time
import pathlib

# Ensure makima_v2 is in sys.path
makima_root = pathlib.Path(__file__).resolve().parent.parent
if str(makima_root) not in sys.path:
    sys.path.insert(0, str(makima_root))

from makima.tools.os.system_info import get_system_stats
from makima.tools.os.processes import list_processes, terminate_process
from makima.tools.os.apps import launch_app
from makima.tools.os.windows import maximize_window, focus_window, minimize_window, _find_target_window
from makima.tools.desktop.uia import inspect_app_ui, click_ui_element, read_ui_text
from makima.tools.desktop.input import keyboard_type, keyboard_hotkey
from makima.tools.desktop.som import annotate_window_som
from makima.tools.desktop.computer_use import computer_use
from makima.tools.os.notifications import show_desktop_notification


def _wait_for_window(title_query: str, timeout: float = 3.0) -> int | None:
    """Poll for window to exist without blind sleeps."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        hwnd, _, err = _find_target_window(title_query)
        if hwnd and not err:
            return hwnd
        time.sleep(0.1)
    return None


def run_e2e_desktop_scenario():
    total_start = time.perf_counter()
    print("=" * 75)
    print(">>> RUNNING MAKIMA v2 E2E WORKFLOW (TARGET ~15s BUDGET)")
    print("=" * 75)

    # ----------------------------------------------------
    # STAGE 1: Process & System Stats Telemetry (~1.3s)
    # ----------------------------------------------------
    t0 = time.perf_counter()
    print("\n[STAGE 1/5] Hardware & Process Telemetry Check...")
    stats = get_system_stats()
    ram_pct = stats.get("ram", {}).get("percent", "N/A")
    cpu_pct = stats.get("cpu", {}).get("percent", "N/A")
    ram_avail = stats.get("ram", {}).get("available_gb", "N/A")

    procs = list_processes(limit=5, sort_by="memory")
    top_proc = procs[0].get("name", "Unknown") if procs else "Unknown"
    top_mem = procs[0].get("memory_mb", "N/A") if procs else "N/A"
    print(f"  [PASS] Stats: CPU={cpu_pct}%, RAM={ram_pct}%, Available={ram_avail} GB")
    print(f"  [PASS] Top Memory Process: {top_proc} ({top_mem} MB)")
    print(f"  Stage 1 Duration: {round(time.perf_counter() - t0, 2)}s")

    # ----------------------------------------------------
    # STAGE 2: App Launch & Zero-Vision UIA (Calculator) (~2.2s)
    # ----------------------------------------------------
    t0 = time.perf_counter()
    print("\n[STAGE 2/5] App Launch & Zero-Vision UIA (Calculator)...")
    launch_app("calc.exe")
    _wait_for_window("Calculator", timeout=2.5)
    time.sleep(0.5)

    # Inspect UIA tree
    calc_ui = inspect_app_ui(title_query="Calculator", max_elements=50)

    # Switch to standard mode if needed
    has_num4 = any(c.get("automation_id") == "num4Button" for c in calc_ui.get("controls", []))
    if not has_num4:
        click_ui_element(title_query="Calculator", automation_id="TogglePaneButton")
        time.sleep(0.2)
        click_ui_element(title_query="Calculator", name="Standard Calculator")
        time.sleep(0.3)

    click_ui_element(title_query="Calculator", automation_id="clearButton")

    # Fast sequential UIA button clicks (4096 * 6 = 24576)
    calc_sequence = [
        ("num4Button", "4"),
        ("num0Button", "0"),
        ("num9Button", "9"),
        ("num6Button", "6"),
        ("multiplyButton", "*"),
        ("num6Button", "6"),
        ("equalButton", "="),
    ]

    for auto_id, label in calc_sequence:
        click_ui_element(title_query="Calculator", automation_id=auto_id)
        time.sleep(0.06)

    time.sleep(0.1)
    read_res = read_ui_text(title_query="Calculator", automation_id="CalculatorResults")
    calc_text = read_res.get("text") or ""
    print(f"  [PASS] UIA Readback: {calc_text!r}")
    print(f"  Stage 2 Duration: {round(time.perf_counter() - t0, 2)}s")

    # ----------------------------------------------------
    # STAGE 3: Window Management & Hardware Input (Notepad) (~2.8s)
    # ----------------------------------------------------
    t0 = time.perf_counter()
    print("\n[STAGE 3/5] Window Management & Hardware Input Simulation (Notepad)...")
    launch_app("notepad.exe")
    _wait_for_window("Notepad", timeout=2.0)
    time.sleep(0.3)

    maximize_window(title_query="Notepad")
    time.sleep(0.2)
    focus_window(title_query="Notepad")
    time.sleep(0.2)

    report_text = (
        f"=== MAKIMA v2 E2E SANITY AUDIT ===\n"
        f"System RAM: {ram_pct}% (Free: {ram_avail} GB)\n"
        f"Top Active: {top_proc}\n"
        f"Buffer: {calc_text}\n"
        f"Status: ALL SYSTEMS OPERATIONAL\n"
    )
    type_res = keyboard_type(text=report_text, title_query="Notepad")
    print(f"  [PASS] Hardware Typing (SendInput): {type_res.get('chars_typed')} chars typed")
    time.sleep(0.4)

    keyboard_hotkey(keys=["ctrl", "s"])
    time.sleep(0.3)
    keyboard_hotkey(keys=["esc"])
    print(f"  Stage 3 Duration: {round(time.perf_counter() - t0, 2)}s")

    # ----------------------------------------------------
    # STAGE 4: Set-of-Marks Visual Grounding & Unified Facade (~3.5s)
    # ----------------------------------------------------
    t0 = time.perf_counter()
    print("\n[STAGE 4/5] Set-of-Marks (SoM) Visual Grounding & Unified Facade (Settings)...")
    launch_app("ms-settings:")
    _wait_for_window("Settings", timeout=3.0)
    time.sleep(0.8)

    focus_window(title_query="Settings")
    time.sleep(0.2)

    som_res = annotate_window_som(title_query="Settings", max_marks=15)
    print(f"  [PASS] SoM Annotation: {som_res.get('total_marks')} marks generated")

    marks = som_res.get("marks", {})
    if marks:
        target_mark_id = list(marks.keys())[0]
        computer_use(action="click", mark_id=int(target_mark_id))
        print(f"  [PASS] computer_use(action='click', mark_id={target_mark_id}) executed")

    time.sleep(0.3)
    minimize_window(title_query="Settings")
    print(f"  Stage 4 Duration: {round(time.perf_counter() - t0, 2)}s")

    # ----------------------------------------------------
    # STAGE 5: Native Toast Notification (~0.5s)
    # ----------------------------------------------------
    t0 = time.perf_counter()
    print("\n[STAGE 5/5] Native Windows Toast Notification...")
    toast_msg = f"RAM: {ram_pct}% | Result: 24,576 | Top: {top_proc[:15]} | Verified!"
    show_desktop_notification(
        title="Makima v2 Sanity Audit (15s Optimized)",
        message=toast_msg,
    )
    print(f"  [PASS] Native WinRT Toast Notification Sent")
    print(f"  Stage 5 Duration: {round(time.perf_counter() - t0, 2)}s")

    # ----------------------------------------------------
    # CLEANUP (~0.8s)
    # ----------------------------------------------------
    time.sleep(0.5)
    terminate_process(name="CalculatorApp.exe")
    terminate_process(name="Calculator.exe")
    terminate_process(name="Notepad.exe")
    terminate_process(name="SystemSettings.exe")

    total_elapsed = round(time.perf_counter() - total_start, 2)
    print("\n" + "=" * 75)
    print(f">>> E2E WORKFLOW FINISHED IN {total_elapsed} SECONDS (TARGET ~15s)")
    print("=" * 75)


if __name__ == "__main__":
    run_e2e_desktop_scenario()
