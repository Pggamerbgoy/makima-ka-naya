import asyncio
import subprocess
from typing import Dict, Any

class TerminalRunner:
    """Async ConPTY / subprocess command runner."""
    async def run(self, cmd: str, timeout: int = 30) -> Dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
        }
