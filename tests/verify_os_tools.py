"""
Verification Test Suite for Phase 2 Step 7: Windows OS, Window & Process Management.
Tests:
  1. Process Management ('makima.tools.os.processes'):
     - list_processes (limit, sorting by cpu, memory, name, pid)
     - get_process_info (by pid, by name, error cases)
     - terminate_process (safety guards against self/system termination)
  2. System Telemetry ('makima.tools.os.system_info'):
     - get_system_stats (CPU %, RAM %, Disk %, Battery status, OS metadata via psutil)
  3. Window Management via pywin32 ('makima.tools.os.windows'):
     - list_open_windows (handle inspection, titles, PIDs, process names, rect, state)
     - Live GUI control (focus_window, minimize_window, maximize_window)
     - Error handling on invalid queries/handles
  4. Application Launching & Process Lifecycle ('makima.tools.os.apps'):
     - launch_app via subprocess.Popen safely
     - argument handling and PATH/WinDir resolution
     - clean process termination verification
  5. Tool Registry Auto-Discovery & Dynamic Schema Synthesis:
     - auto_discover discovers all 9 OS tools
     - dynamic schema validation
     - async tool execution via ToolRegistry.execute
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import psutil

from makima.tools.os import (
    focus_window,
    get_process_info,
    get_system_stats,
    launch_app,
    list_open_windows,
    maximize_window,
    minimize_window,
    terminate_process,
)
from makima.tools.os.processes import list_processes
from makima.tools.registry import get_registry, reset_registry


def test_process_management():
    print("\n" + "=" * 60)
    print("[TEST 1] Process Management (makima.tools.os.processes)")
    print("=" * 60)

    # 1. list_processes with limit and cpu sort
    procs_cpu = list_processes(limit=10, sort_by="cpu")
    assert isinstance(procs_cpu, list), "list_processes should return a list"
    assert len(procs_cpu) <= 10, "list_processes limit not respected"
    assert len(procs_cpu) > 0, "list_processes should return running processes"
    first = procs_cpu[0]
    for key in ("pid", "name", "cpu_percent", "memory_percent", "status"):
        assert key in first, f"Missing key '{key}' in process item: {first}"
    print(f"  [PASS] list_processes(limit=10, sort_by='cpu') returned {len(procs_cpu)} processes.")

    # 2. list_processes sorted by memory
    procs_mem = list_processes(limit=5, sort_by="memory")
    assert len(procs_mem) <= 5
    mem_percents = [p["memory_percent"] for p in procs_mem]
    assert mem_percents == sorted(mem_percents, reverse=True), "Processes not sorted by memory descending"
    print(f"  [PASS] list_processes(limit=5, sort_by='memory') sorted correctly: {mem_percents}")

    # 3. list_processes sorted by name
    procs_name = list_processes(limit=5, sort_by="name")
    assert len(procs_name) <= 5
    names = [(p["name"] or "").lower() for p in procs_name]
    assert names == sorted(names), "Processes not sorted alphabetically by name"
    print(f"  [PASS] list_processes(limit=5, sort_by='name') sorted correctly: {names}")

    # 4. get_process_info for current process (self)
    my_pid = os.getpid()
    info = get_process_info(pid=my_pid)
    assert info.get("success") is True, f"Failed getting info for own process: {info}"
    assert info["pid"] == my_pid
    assert "python" in (info["name"] or "").lower()
    assert info["status"] in ("running", "active")
    assert "memory_percent" in info
    assert "memory_rss_mb" in info
    print(f"  [PASS] get_process_info(pid={my_pid}) verified for current process '{info['name']}'.")

    # 5. get_process_info by name
    info_by_name = get_process_info(name="python")
    assert info_by_name.get("success") is True
    assert "python" in (info_by_name["name"] or "").lower()
    print(f"  [PASS] get_process_info(name='python') found PID {info_by_name['pid']}.")

    # 6. get_process_info missing parameters error handling
    empty_info = get_process_info()
    assert empty_info.get("success") is False
    assert "error" in empty_info
    print(f"  [PASS] get_process_info() with missing params handled safely: {empty_info['error']}")

    # 7. Safety guards: refuse to terminate self
    self_term = terminate_process(pid=my_pid)
    assert self_term.get("success") is False
    assert "Cannot terminate the current Makima process" in self_term["error"]
    print(f"  [PASS] terminate_process self-termination guard verified: {self_term['error']}")

    # 8. Safety guards: refuse to terminate PID 0 / protected system
    sys_term = terminate_process(pid=0)
    assert sys_term.get("success") is False
    assert "protected system process" in sys_term["error"]
    print(f"  [PASS] terminate_process system-PID guard verified: {sys_term['error']}")


def test_system_telemetry():
    print("\n" + "=" * 60)
    print("[TEST 2] System Telemetry (makima.tools.os.system_info)")
    print("=" * 60)

    stats = get_system_stats()
    assert isinstance(stats, dict), "get_system_stats must return a dict"

    # CPU
    cpu = stats.get("cpu", {})
    assert "percent" in cpu and 0.0 <= cpu["percent"] <= 100.0, f"Invalid CPU percent: {cpu}"
    assert cpu.get("cores_logical", 0) > 0, "Logical cores must be > 0"
    print(f"  [PASS] CPU: {cpu['percent']}% ({cpu['cores_logical']} logical cores, {cpu.get('cores_physical')} physical)")

    # RAM
    ram = stats.get("ram", {})
    assert "percent" in ram and 0.0 <= ram["percent"] <= 100.0, f"Invalid RAM percent: {ram}"
    assert ram.get("total_gb", 0) > 0, "Total RAM must be > 0"
    assert ram.get("used_gb", 0) > 0, "Used RAM must be > 0"
    print(f"  [PASS] RAM: {ram['percent']}% ({ram['used_gb']} GB / {ram['total_gb']} GB)")

    # Disk
    disk = stats.get("disk", {})
    assert "percent" in disk and 0.0 <= disk["percent"] <= 100.0, f"Invalid Disk percent: {disk}"
    assert disk.get("total_gb", 0) > 0, "Total Disk must be > 0"
    assert "partitions" in disk and isinstance(disk["partitions"], list)
    print(f"  [PASS] Disk: {disk['percent']}% ({disk['used_gb']} GB / {disk['total_gb']} GB on {disk['system_drive']})")

    # Battery
    battery = stats.get("battery", {})
    assert "has_battery" in battery and isinstance(battery["has_battery"], bool)
    assert "power_plugged" in battery
    print(f"  [PASS] Battery: has_battery={battery['has_battery']}, plugged={battery['power_plugged']}, percent={battery['percent']}")

    # OS
    os_info = stats.get("os", {})
    assert os_info.get("system") == "Windows", f"Expected Windows system: {os_info}"
    assert "release" in os_info and "version" in os_info
    assert os_info.get("uptime_seconds", -1) >= 0
    print(f"  [PASS] OS: {os_info['system']} {os_info['release']} ({os_info['machine']}), uptime: {os_info['uptime_seconds']}s")


def test_app_launch_and_process_lifecycle():
    print("\n" + "=" * 60)
    print("[TEST 3] App Launching & Process Lifecycle (makima.tools.os.apps)")
    print("=" * 60)

    # 1. Launch notepad.exe
    launch_res = launch_app("notepad.exe")
    assert launch_res.get("success") is True, f"Failed launching notepad: {launch_res}"
    pid = launch_res.get("pid")
    assert pid is not None and pid > 0, "Invalid PID returned"
    assert psutil.pid_exists(pid), f"PID {pid} does not exist in operating system"
    print(f"  [PASS] launch_app('notepad.exe') successfully spawned PID {pid}")

    # 2. Inspect spawned process
    p_info = get_process_info(pid=pid)
    assert p_info.get("success") is True
    assert "notepad" in (p_info.get("name") or "").lower()
    print(f"  [PASS] get_process_info confirmed process '{p_info['name']}' is running.")

    # 3. Terminate process gracefully
    term_res = terminate_process(pid=pid, force=False)
    assert term_res.get("success") is True, f"Failed to terminate PID {pid}: {term_res}"
    time.sleep(0.3)
    assert not psutil.pid_exists(pid), f"PID {pid} is still alive after termination"
    print(f"  [PASS] terminate_process successfully ended PID {pid}")

    # 4. Launch app with args
    cmd_res = launch_app("cmd.exe", ["/c", "exit 0"])
    assert cmd_res.get("success") is True
    print(f"  [PASS] launch_app with list args succeeded (PID: {cmd_res['pid']})")

    # 5. Launch app with string args
    cmd_str_res = launch_app("cmd.exe", "/c exit 0")
    assert cmd_str_res.get("success") is True
    print(f"  [PASS] launch_app with string args succeeded (PID: {cmd_str_res['pid']})")

    # 6. Error handling for non-existent app
    bad_res = launch_app("nonexistent_binary_makima_test_9999.exe")
    assert bad_res.get("success") is False
    assert "error" in bad_res
    print(f"  [PASS] launch_app non-existent binary handled safely: {bad_res['error']}")


def test_windows_management():
    print("\n" + "=" * 60)
    print("[TEST 4] Windows Management via pywin32 (makima.tools.os.windows)")
    print("=" * 60)

    # 1. list_open_windows
    windows = list_open_windows()
    assert isinstance(windows, list), "list_open_windows must return a list"
    assert len(windows) > 0, "list_open_windows should find open windows"

    sample = windows[0]
    for key in ("hwnd", "title", "pid", "process_name", "state", "rect"):
        assert key in sample, f"Missing key '{key}' in window dict: {sample}"
    assert isinstance(sample["hwnd"], int), "HWND should be int"
    assert isinstance(sample["title"], str) and sample["title"], "Window title must be non-empty"
    assert sample["state"] in ("normal", "minimized", "maximized")
    assert "width" in sample["rect"] and "height" in sample["rect"]

    print(f"  [PASS] list_open_windows discovered {len(windows)} open titled windows.")
    print(f"         Sample window: HWND {sample['hwnd']} | '{sample['title'][:35]}' | PID {sample['pid']} ({sample['process_name']})")

    # 2. Live GUI control with a spawned application
    launch_res = launch_app("notepad.exe")
    notepad_pid = launch_res["pid"]
    try:
        # Allow window creation
        time.sleep(1.2)

        # Discover notepad window
        notepad_wins = [
            w for w in list_open_windows()
            if w["pid"] == notepad_pid or "notepad" in w["title"].lower() or "notepad" in w["process_name"].lower()
        ]
        assert len(notepad_wins) > 0, f"Could not find window for notepad process (PID: {notepad_pid})"
        target_win = notepad_wins[0]
        notepad_hwnd = target_win["hwnd"]
        print(f"  [PASS] Found notepad window HWND: {notepad_hwnd} (Title: '{target_win['title']}')")

        # 3. Test focus_window
        focus_res = focus_window(hwnd=notepad_hwnd)
        assert focus_res.get("success") is True, f"focus_window failed: {focus_res}"
        print(f"  [PASS] focus_window(hwnd={notepad_hwnd}) succeeded.")

        # Test focus by title query
        focus_title_res = focus_window(title_query="Notepad")
        assert focus_title_res.get("success") is True, f"focus_window by title query failed: {focus_title_res}"
        print(f"  [PASS] focus_window(title_query='Notepad') succeeded.")

        # 4. Test minimize_window
        min_res = minimize_window(hwnd=notepad_hwnd)
        assert min_res.get("success") is True, f"minimize_window failed: {min_res}"
        print(f"  [PASS] minimize_window(hwnd={notepad_hwnd}) succeeded.")

        # 5. Test maximize_window
        max_res = maximize_window(hwnd=notepad_hwnd)
        assert max_res.get("success") is True, f"maximize_window failed: {max_res}"
        print(f"  [PASS] maximize_window(hwnd={notepad_hwnd}) succeeded.")

        # Restore and refocus
        refocus_res = focus_window(hwnd=notepad_hwnd)
        assert refocus_res.get("success") is True

    finally:
        # Clean up spawned test app
        terminate_process(pid=notepad_pid, force=True)
        time.sleep(0.2)

    # 6. Window error handling
    invalid_win = focus_window(hwnd=99999999)
    assert invalid_win.get("success") is False
    assert "error" in invalid_win
    print(f"  [PASS] focus_window invalid HWND handled safely: {invalid_win['error']}")

    empty_win = focus_window()
    assert empty_win.get("success") is False
    print(f"  [PASS] focus_window missing params handled safely: {empty_win['error']}")


async def test_tool_registry_and_schema_synthesis():
    print("\n" + "=" * 60)
    print("[TEST 5] Tool Registry Auto-Discovery & Schema Synthesis")
    print("=" * 60)

    reset_registry()
    reg = get_registry(auto_discover=True)

    expected_os_tools = [
        "list_processes",
        "get_process_info",
        "terminate_process",
        "list_open_windows",
        "focus_window",
        "minimize_window",
        "maximize_window",
        "launch_app",
        "get_system_stats",
    ]

    for tool_name in expected_os_tools:
        assert tool_name in reg, f"Expected OS tool '{tool_name}' not found in registry"
        tool_obj = reg[tool_name]
        schema = tool_obj.to_dict()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool_name
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        print(f"  [PASS] Tool '{tool_name}' auto-discovered with schema: {len(tool_obj.tags)} tags")

    # Execute get_system_stats via registry engine
    sys_result = await reg.execute("get_system_stats")
    assert isinstance(sys_result, dict)
    assert "cpu" in sys_result and "ram" in sys_result
    print("  [PASS] Asynchronous execution of 'get_system_stats' via ToolRegistry.execute succeeded.")

    # Execute list_processes via registry engine with arguments
    proc_result = await reg.execute("list_processes", {"limit": 3, "sort_by": "memory"})
    assert isinstance(proc_result, list) and len(proc_result) <= 3
    print(f"  [PASS] Asynchronous execution of 'list_processes' via ToolRegistry.execute returned {len(proc_result)} processes.")


def main():
    print("Starting Standalone Verification Test Suite for Windows OS Management...")
    t0 = time.time()

    test_process_management()
    test_system_telemetry()
    test_app_launch_and_process_lifecycle()
    test_windows_management()
    asyncio.run(test_tool_registry_and_schema_synthesis())

    elapsed = round(time.time() - t0, 2)
    print("\n" + "=" * 60)
    print(f"ALL TESTS PASSED SUCCESSFULLY in {elapsed}s (Exit Code: 0)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
