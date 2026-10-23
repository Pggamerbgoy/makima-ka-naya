"""
tests/test_smoke.py — Pytest-native unit & smoke test suite for Makima v2 (Step 23.3).
Designed for standard `python -m pytest` test runner with assert-based tests.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from makima.config import get_settings
from makima.core.context import ContextCompressor
from makima.core.guardrails import DangerousCommandError, Guardrails
from makima.core.telemetry import StructuredTelemetry
from makima.memory.episodic import EpisodicMemory
from makima.memory.state import StateMemory
from makima.provider.adapters.base import Message
from makima.tools.automation import cronjob_manage, shutdown_scheduler
from makima.tools.desktop.uia import inspect_app_ui, read_ui_text, set_ui_text
from makima.tools.documents import read_document
from makima.tools.media import play_song
from makima.tools.os import (
    launch_application,
    show_desktop_notification,
)
from makima.tools.os.apps import launch_app
from makima.tools.os.processes import terminate_process
from makima.tools.os.windows import _find_target_window
from makima.tools.registry import ToolRegistry, tool
from makima.tools.web_search import fetch_page, web_search
import time
import win32con
import win32gui


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------
def test_config_smoke():
    settings = get_settings(force_reload=True)
    assert settings.app.name == "Makima"
    assert settings.app.version == "2.0.0"
    assert "ollama" in settings.providers.backends
    assert settings.data_dir_path.name == ".makima"


# ---------------------------------------------------------------------------
# Tool Registry Tests
# ---------------------------------------------------------------------------
def test_tool_registry_smoke():
    reg = ToolRegistry(name="smoke_test")

    @tool(name="sample_tool", description="A test tool", tags=["test"])
    def sample_tool(val: int) -> int:
        return val * 2

    reg.register(sample_tool)
    assert reg.has("sample_tool")

    schemas = reg.get_schemas(format="openai")
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "sample_tool"

    res = asyncio.run(reg.execute("sample_tool", {"val": 21}))
    assert res == 42


# ---------------------------------------------------------------------------
# Guardrails Tests
# ---------------------------------------------------------------------------
def test_guardrails_smoke():
    gr = Guardrails()

    # Destructive command should be blocked
    with pytest.raises(DangerousCommandError):
        gr.validate_command("rm -rf /")

    with pytest.raises(DangerousCommandError):
        gr.validate_command("DROP TABLE users;")

    # Safe command should pass
    gr.validate_command("dir")
    gr.validate_command("git status")

    # Secret filter
    filtered = gr.filter_secrets("My key is AIzaSyD1234567890abcdef1234567890abcde")
    assert "AIzaSy" not in filtered or "[REDACTED" in filtered


# ---------------------------------------------------------------------------
# Context Compressor Tests
# ---------------------------------------------------------------------------
def test_context_compressor_smoke():
    comp = ContextCompressor(max_tokens=100, head_turns=1, tail_turns=1)
    messages = [
        Message(role="user", content="Goal: Build an app"),
        Message(role="assistant", content="Step 1 doing X " * 20),
        Message(role="tool", content="Output of step 1 " * 20),
        Message(role="assistant", content="Step 2 doing Y " * 20),
        Message(role="user", content="Final question: What was step 1?"),
    ]
    assert comp.needs_compression(messages, system_prompt="System instructions")
    compressed = comp.compress(messages, system_prompt="System instructions")
    assert len(compressed) < len(messages)
    assert compressed[0].content == "Goal: Build an app"
    assert "Final question" in compressed[-1].content


# ---------------------------------------------------------------------------
# Memory Subsystem Tests
# ---------------------------------------------------------------------------
def test_memory_state_smoke():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        user_md = tmp_path / "USER.md"
        user_md.write_text("# User Profile\n- Name: Alice\n", encoding="utf-8")
        mem_md = tmp_path / "MEMORY.md"
        mem_md.write_text("# Knowledge\n- Project Makima\n", encoding="utf-8")

        sm = StateMemory(data_dir=tmp_path)
        injection = sm.format_prompt_injection()
        assert "Alice" in injection
        assert "Project Makima" in injection


@pytest.mark.asyncio
async def test_episodic_memory_smoke():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test_ep.db"
        ep = EpisodicMemory(db_path=db_path)
        await ep.connect()

        await ep.store_turn(
            session_id="test_sess",
            turn_index=1,
            role="user",
            content="Hello Makima!",
        )
        turns = await ep.get_recent_turns(session_id="test_sess", limit=5)
        assert len(turns) == 1
        assert turns[0]["content"] == "Hello Makima!"

        await ep.close()


# ---------------------------------------------------------------------------
# Structured Telemetry Tests
# ---------------------------------------------------------------------------
def test_telemetry_smoke():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tel = StructuredTelemetry(log_dir=tmp_dir, buffer_size=20)
        tel.emit_sync("smoke.event", {"status": "ok"})
        recent = tel.get_recent(5)
        assert len(recent) == 1
        assert recent[0]["event"] == "smoke.event"
        assert recent[0]["status"] == "ok"


# ---------------------------------------------------------------------------
# Fast Web Search Smoke Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_web_search_smoke():
    empty_res = await web_search("")
    assert empty_res == []

    bad_url = await fetch_page("https://invalid-host-testing-smoke.invalid")
    assert isinstance(bad_url, dict)
    assert bad_url.get("error") is not None or bad_url.get("status_code", 0) >= 400


# ---------------------------------------------------------------------------
# Automation & Cronjob Smoke Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cronjob_smoke():
    try:
        created = await cronjob_manage(
            action="create",
            name="smoke_cron",
            prompt="smoke prompt",
            schedule="0 12 * * *",
        )
        assert created.get("status") == "created"
        assert created.get("name") == "smoke_cron"

        jobs_list = await cronjob_manage(action="list")
        assert jobs_list.get("status") == "success"
        assert any(j["name"] == "smoke_cron" for j in jobs_list.get("jobs", []))

        removed = await cronjob_manage(action="remove", name="smoke_cron")
        assert removed.get("status") == "removed"
    finally:
        shutdown_scheduler(wait=False)


# ---------------------------------------------------------------------------
# Document Ingestion Smoke Test (MarkItDown)
# ---------------------------------------------------------------------------
def test_read_document_smoke(tmp_path: Path):
    sample = tmp_path / "smoke.txt"
    sample.write_text("Smoke test document text.", encoding="utf-8")
    res = read_document(str(sample))
    assert res["status"] == "success"
    assert "Smoke test" in res["markdown"]


# ---------------------------------------------------------------------------
# Media Playback Smoke Test (YouTube / Spotify)
# ---------------------------------------------------------------------------
def test_play_song_smoke():
    res = play_song("Never Gonna Give You Up", platform="youtube", auto_open=False)
    assert res["status"] == "success"
    assert res["platform"] == "youtube"
    assert "dQw4w9WgXcQ" in res["url"] or "youtube.com" in res["url"]


# ---------------------------------------------------------------------------
# AppOpener Controller Smoke Test
# ---------------------------------------------------------------------------
def test_app_opener_smoke():
    res = launch_application("calc:", dry_run=True)
    assert res["success"] is True
    assert res["dry_run"] is True


# ---------------------------------------------------------------------------
# Desktop Notification Smoke Test (win11toast)
# ---------------------------------------------------------------------------
def test_desktop_notification_smoke():
    res = show_desktop_notification(
        title="Makima Smoke Test",
        message="Running automated smoke test.",
        wait=False,
    )
    assert res["success"] is True
    assert res["dispatched"] is True


# ---------------------------------------------------------------------------
# Interactive Desktop App Lifecycle Test (Step 29 / Zero-Vision UIA)
# ---------------------------------------------------------------------------
def test_interactive_app_lifecycle_smoke(tmp_path: Path):
    test_file = tmp_path / "smoke_doc.txt"
    test_file.write_text("Smoke test baseline\n", encoding="utf-8")

    launch_res = launch_app("notepad.exe", args=[str(test_file)])
    assert launch_res.get("success") is True
    time.sleep(1.5)

    try:
        hwnd, _, _ = _find_target_window(title_query="smoke_doc")
        if not hwnd:
            hwnd, _, _ = _find_target_window(title_query="Notepad")
        assert hwnd is not None

        # Zero-vision UI inspection
        ui = inspect_app_ui(hwnd=hwnd, max_elements=10)
        assert ui.get("success") is True

        # Interactive UI text writing
        set_res = set_ui_text(hwnd=hwnd, control_type="Edit", text="Smoke test interactive content verified")
        assert set_res.get("success") is True

        # Read back live UI text
        read_res = read_ui_text(hwnd=hwnd, control_type="Edit")
        assert "Smoke test interactive content verified" in (read_res.get("text") or "")

        # Save to disk via WM_COMMAND
        win32gui.SendMessage(hwnd, win32con.WM_COMMAND, 3, 0)
        time.sleep(0.5)

        # Clean close then terminate
        win32gui.SendMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)
        terminate_process(name="notepad.exe")

        # Assert disk persistence
        saved_disk = test_file.read_text(encoding="utf-8")
        assert "Smoke test interactive content verified" in saved_disk
    finally:
        terminate_process(name="notepad.exe")


# ---------------------------------------------------------------------------
# Astra-Grade Computer Use Smoke Test
# ---------------------------------------------------------------------------
def test_computer_use_smoke(tmp_path: Path):
    from makima.tools.desktop.computer_use import computer_use
    from makima.tools.os.apps import launch_app
    from makima.tools.os.processes import terminate_process

    pos = computer_use(action="cursor_position")
    assert "x" in pos and "y" in pos

    launch_res = launch_app("notepad.exe")
    assert launch_res.get("success") is True
    time.sleep(1.0)

    try:
        scr = computer_use(action="screenshot", title_query="Notepad")
        assert scr.get("success") is True
        assert "image_path" in scr
        # Clean up test capture image
        try:
            p = Path(scr["image_path"])
            if p.exists():
                p.unlink()
        except Exception:
            pass
    finally:
        terminate_process(name="notepad.exe")


# ---------------------------------------------------------------------------
# Hermes Preference & Memory Tools Smoke Test
# ---------------------------------------------------------------------------
def test_preference_memory_tools_smoke(tmp_path: Path):
    from makima.tools.memory import (
        remember_user_preference,
        remember_fact,
        get_user_profile,
        get_memory_facts,
        forget_fact,
    )
    import makima.tools.memory as mem_mod
    original_sm = mem_mod.StateMemory
    mem_mod.StateMemory = lambda: StateMemory(data_dir=tmp_path)

    try:
        # Save preference
        p_res = remember_user_preference("User prefers concise code and dark themes")
        assert p_res["success"] is True

        # Read back profile
        prof = get_user_profile()
        assert prof["success"] is True
        assert "dark themes" in prof["content"]

        # Save fact
        f_res = remember_fact("Makima v2 is an autonomous AI desktop assistant", category="Projects")
        assert f_res["success"] is True

        # Read back facts
        facts = get_memory_facts()
        assert facts["success"] is True
        assert any("autonomous" in f for f in facts["facts"])

        # Forget fact
        forgot = forget_fact("Makima v2")
        assert forgot["success"] is True
    finally:
        mem_mod.StateMemory = original_sm


# ---------------------------------------------------------------------------
# SOTA Interactive Browser Automation Smoke Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_interactive_browser_smoke(tmp_path: Path):
    from makima.tools.browser.automation import browser_interact

    sample_html = tmp_path / "smoke_browser.html"
    sample_html.write_text(
        "<html><head><title>Makima Browser</title></head><body><h1>Makima Browser</h1>"
        "<input id='kw' value='' />"
        "<button onclick='document.title=\"Clicked OK\"'>Submit</button>"
        "</body></html>",
        encoding="utf-8",
    )
    url = f"file:///{sample_html.resolve().as_posix()}"

    try:
        # Navigate
        nav = await browser_interact(action="navigate", url=url, headless=True)
        assert nav.get("success") is True
        assert "Makima Browser" in nav.get("title", "")
        assert nav.get("total_elements", 0) >= 2

        # Type into first input
        type_res = await browser_interact(action="type", index=1, text="Makima Query")
        assert type_res.get("success") is True

        # Click button (index 2)
        click_res = await browser_interact(action="click", index=2)
        assert click_res.get("success") is True
        assert click_res.get("title") == "Clicked OK"
    finally:
        await browser_interact(action="close")


# ---------------------------------------------------------------------------
# Implicit Preference Learner Smoke Test (Step 39)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_implicit_preference_learner_smoke(tmp_path: Path):
    from makima.memory.reflection import ImplicitPreferenceLearner
    from makima.memory.state import StateMemory

    sm = StateMemory(data_dir=tmp_path)
    learner = ImplicitPreferenceLearner(state_memory=sm, enable_llm_reflection=False)

    # 1. Heuristic extraction
    extracted = learner.extract_heuristically("No, don't use Chrome, use Brave instead")
    assert extracted == "Prefers Brave instead of Chrome"

    # 2. Transient command filter
    transient = learner.extract_heuristically("click button 4")
    assert transient is None

    # 3. Learn from turn & persist
    learned = await learner.learn_from_turn(
        user_message="I prefer using Brave browser",
        assistant_response="Understood!",
    )
    assert learned == "Prefers Brave browser"
    assert "Prefers Brave browser" in sm.read_user_profile()

    # 4. Deduplication
    learned_again = await learner.learn_from_turn(
        user_message="I prefer using Brave browser",
        assistant_response="Already noted.",
    )
    assert learned_again is None


# ---------------------------------------------------------------------------
# Context-Aware Suggested Replies Extraction Smoke Test
# ---------------------------------------------------------------------------
def test_engine_suggestions_extraction():
    from makima.core.engine import HermesAgentEngine, EngineResult

    # 1. Normal suggestions extraction
    raw = (
        "Here are 3 tips to speed up Windows:\n"
        "1. Check Task Manager\n"
        "2. Disable startup apps\n\n"
        "```suggestions\n"
        '["Kya disk usage 100% hai?", "Task Manager khol kar dekha?", "SSD ya HDD hai?"]\n'
        "```"
    )
    clean, suggestions = HermesAgentEngine._extract_suggestions(raw)
    assert "```suggestions" not in clean
    assert "Check Task Manager" in clean
    assert len(suggestions) == 3
    assert suggestions[0] == "Kya disk usage 100% hai?"
    assert suggestions[2] == "SSD ya HDD hai?"

    # 2. Text without suggestions block
    plain = "This is a plain response without suggestions."
    clean_plain, plain_suggs = HermesAgentEngine._extract_suggestions(plain)
    assert clean_plain == plain
    assert plain_suggs == []

    # 3. Malformed JSON resilience
    malformed = "Some answer.\n```suggestions\n[not valid json\n```"
    clean_bad, bad_suggs = HermesAgentEngine._extract_suggestions(malformed)
    assert bad_suggs == []

    # 4. Empty text
    empty_clean, empty_suggs = HermesAgentEngine._extract_suggestions("")
    assert empty_clean == ""
    assert empty_suggs == []

    # 5. EngineResult defaults
    result = EngineResult(
        content=clean,
        messages=[],
        turn_count=1,
        tool_calls_executed=0,
        completed=True,
        suggestions=suggestions,
    )
    assert len(result.suggestions) == 3





