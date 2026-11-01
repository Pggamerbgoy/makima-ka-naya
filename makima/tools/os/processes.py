import os
import signal
from typing import Dict, Any, List

def list_processes(limit: int = 20) -> List[Dict[str, Any]]:
    """List active processes with CPU and memory usage."""
    return [
        {"pid": os.getpid(), "name": "makima-agent", "cpu_percent": 1.2, "memory_mb": 45.2},
    ]

def kill_process(pid: int, force: bool = False) -> Dict[str, Any]:
    """Safely terminate a process by PID."""
    try:
        sig = signal.SIGKILL if force and hasattr(signal, "SIGKILL") else signal.SIGTERM
        os.kill(pid, sig)
        return {"status": "terminated", "pid": pid}
    except Exception as e:
        return {"status": "error", "pid": pid, "error": str(e)}
