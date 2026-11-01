import platform
import os
from typing import Dict, Any

def get_system_diagnostics() -> Dict[str, Any]:
    """Retrieve host OS, CPU architecture, memory, and python environment details."""
    return {
        "os": platform.system(),
        "release": platform.release(),
        "arch": platform.machine(),
        "processor": platform.processor() or "Multi-core",
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 4,
        "hostname": platform.node(),
    }
