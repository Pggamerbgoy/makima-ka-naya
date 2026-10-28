from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_scheduled_job_uses_default_notification_when_no_handler_is_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from makima.tools.automation import cronjob

    delivered: list[dict[str, Any]] = []
    monkeypatch.setattr(cronjob, "_NOTIFICATION_HANDLERS", [])
    monkeypatch.setattr(
        cronjob,
        "_send_default_notification",
        lambda payload: delivered.append(payload) or True,
    )

    result = await cronjob._cron_job_executor(
        job_id="cronjob-test",
        name="hydration-reminder",
        prompt="Drink some water.",
    )

    assert len(delivered) == 1
    assert delivered[0]["job_id"] == "cronjob-test"
    assert delivered[0]["prompt"] == "Drink some water."
    assert result["handlers_notified"] == 1
