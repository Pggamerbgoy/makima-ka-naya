import asyncio
import shlex
from typing import Dict, Any

class SubprocessRunner:
    """Safe asynchronous command executor with timeout and signal handling."""
    def __init__(self, default_timeout: int = 45):
        self.default_timeout = default_timeout

    async def run_command(self, cmd: str, timeout: int = None) -> Dict[str, Any]:
        t = timeout or self.default_timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=t)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"stdout": "", "stderr": f"Command timed out after {t}s", "exit_code": -1, "timed_out": True}
