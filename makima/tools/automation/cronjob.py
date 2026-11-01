import time
from typing import Dict, Any, List, Callable

class CronJobScheduler:
    """Scheduled periodic triggers and proactive reminders."""
    def __init__(self):
        self.jobs: List[Dict[str, Any]] = []

    def add_job(self, name: str, interval_seconds: int, action: str) -> Dict[str, Any]:
        job = {
            "name": name,
            "interval_seconds": interval_seconds,
            "action": action,
            "created_at": time.time(),
            "active": True,
        }
        self.jobs.append(job)
        return {"status": "scheduled", "job": job}

    def list_jobs(self) -> List[Dict[str, Any]]:
        return self.jobs
