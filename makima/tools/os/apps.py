import os
import subprocess
import platform
from typing import Dict, Any

def launch_app(app_name: str) -> Dict[str, Any]:
    """Launch or focus a desktop application on Windows, Mac, or Linux."""
    system = platform.system().lower()
    try:
        if system == "windows":
            os.startfile(app_name) # type: ignore
        elif system == "darwin":
            subprocess.Popen(["open", "-a", app_name])
        else:
            subprocess.Popen([app_name], shell=True)
        return {"status": "success", "app": app_name, "message": f"Launched {app_name}"}
    except Exception as e:
        return {"status": "error", "app": app_name, "error": str(e)}
