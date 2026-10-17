# 📋 Makima v2 — Master Implementation TODO Checklist
> **Rule**: Every step requires (1) Sub-task checklist, (2) Data Flow & Call-Graph Map, and (3) Live Verification Script execution before marking as completed `[x]`.

---

## 🟢 Phase 1: The Brain & Model Gateway

### Step 1: Dynamic Configuration Engine (`makima/config.py`)
- [x] 1.1 Create `makima/config.py` using `pydantic-settings` to load `configs/settings.yaml` and `.env`.
- [x] 1.2 Implement dynamic path resolution (`~/.makima`, `workspace_dir`, `sqlite_path`) without hardcoded OS paths.
- [x] 1.3 Add dynamic provider credentials auto-detection from environment variables (`*_API_KEY`).
- [x] 1.4 Write and run `tests/verify_config.py` (live test config loading, defaults, and env overrides).
- **Status**: ✅ Completed (Verified via tests/verify_config.py & Ruflo Complexity Analysis)

### Step 2: Provider Adapters & Circuit Breakers (`makima/provider/`)
- [x] 2.1 Implement `makima/provider/circuit_breaker.py` (3-state: closed/open/half_open with jittered cooldown).
- [x] 2.2 Implement `makima/provider/adapters/base.py` (Abstract `BaseProvider` contract).
- [x] 2.3 Implement `makima/provider/adapters/gemini.py` (Google GenAI SDK adapter with free-tier streaming).
- [x] 2.4 Implement `makima/provider/adapters/openai_compatible.py` (Groq free, OpenRouter free, Cerebras, Ollama).
- [x] 2.5 Write and run `tests/verify_providers.py` (live test provider adapters with real/mock fallback).
- **Status**: ✅ Completed (Verified with 5 passing test suites in tests/verify_providers.py)

### Step 3: Dynamic Zero-Cost ParetoRouter (`makima/provider/router.py`)
- [x] 3.1 Implement dynamic backend discovery (probe active env keys + Ollama `/api/tags` on localhost:11434).
- [x] 3.2 Implement task cascades (`fast_chat`, `code`, `deep_reasoning`, `vision`, `offline`).
- [x] 3.3 Implement Pareto frontier sorting: `(is_preferred, task_idx, latency_tier, ewma_ms, fail_count)`.
- [x] 3.4 Implement EWMA latency tracking ($\alpha=0.25$) and multi-key rotation on 429.
- [x] 3.5 Write and run `tests/verify_router.py` (simulate rate limits and verify auto-cascade fallback).
- **Status**: ✅ Completed (Verified via tests/verify_router.py with 4/4 passing suites)

### Step 4: Hermes Core While-Loop & Context Compressor (`makima/core/`)
- [x] 4.1 Implement `makima/core/engine.py` (Hermes-style autonomous while-loop: prompt + tools -> model -> parse tool calls -> execute -> append -> repeat).
- [x] 4.2 Implement `makima/core/context.py` (Dynamic context budgeting & middle-turn compressor protecting Head & Tail).
- [x] 4.3 Implement `makima/core/guardrails.py` (Dangerous command block, secret leak entropy scan >4.5, XML isolation framing).
- [x] 4.4 Write and run `tests/verify_engine.py` (simulate multi-turn chat with mock tool execution).
- **Status**: ✅ Completed (Verified via tests/verify_engine.py with 7/7 passing suites)

---

## 🟡 Phase 2: Modular Toolsets & OS Control

### Step 5: Dynamic Tool Registry & Auto-Discovery (`makima/tools/`)
- [x] 5.1 Implement `makima/tools/registry.py` with `@tool(name, description, tags)` decorator.
- [x] 5.2 Implement automatic JSON schema synthesis from Python type annotations using Pydantic v2.
- [x] 5.3 Implement dynamic directory auto-scanner (`tools/**/`) using `importlib` and `pkgutil`.
- [x] 5.4 Implement `[TOOL_FAILED: name]` fallback error generator with domain-specific alternative hints.
- [x] 5.5 Write and run `tests/verify_tool_registry.py` (register dummy tool, verify schema auto-generation).
- **Status**: ✅ Completed (Verified via tests/verify_tool_registry.py with 6/6 passing suites)

### Step 6: Safe Filesystem & SAGA Rollback (`makima/tools/filesystem/`)
- [x] 6.1 Implement `safe_io.py`: read, write, edit, delete with strict workspace boundary clamping.
- [x] 6.2 Implement `saga_rollback.py`: pre-state file snapshotting and `restore_snapshot` for undo command.
- [x] 6.3 Write and run `tests/verify_filesystem.py` (write file, edit, snapshot, undo).
- **Status**: ✅ Completed (Verified via tests/verify_filesystem.py with 9/9 passing suites)

### Step 7: Windows OS, Window & Process Management (`makima/tools/os/`)
- [x] 7.1 Implement `apps.py`: App search and launch with verified PID tracking.
- [x] 7.2 Implement `windows.py`: Window focus, minimize, maximize, snap via `pywin32`.
- [x] 7.3 Implement `processes.py`: Process CPU/RAM monitoring and safe kill via `psutil`.
- [x] 7.4 Implement `system_info.py`: Battery, disk, hardware diagnostic stats.
- [x] 7.5 Write and run `tests/verify_os_tools.py` (list open windows, get CPU stats).
- **Status**: ✅ Completed (Verified via tests/verify_os_tools.py with 5/5 passing suites in 10.1s)

### Step 8: Sandboxed Terminal & ConPTY Runner (`makima/tools/terminal/`)
- [x] 8.1 Implement async subprocess runner with strict timeout and working directory clamping.
- [x] 8.2 Implement Windows ConPTY virtual terminal emulation using `pywinpty` for interactive prompts.
- [x] 8.3 Implement dangerous command blocker (`rm -rf`, format, DROP TABLE).
- [x] 8.4 Write and run `tests/verify_terminal.py` (run safe command, test timeout, test dangerous command block).
- **Status**: ✅ Completed (Verified via tests/verify_terminal.py with 7/7 passing suites in 5.3s)

### Step 9: Web Browser, Media & Document Tools (`makima/tools/`)
- [x] 9.1 Implement `tools/browser/`: Fast HTTP page fetcher & web search via `httpx`, plus Playwright automation.
- [x] 9.2 Implement `tools/media/`: Native Windows Media Control (`winrt`) for Spotify/YouTube and master volume (`pycaw`).
- [x] 9.3 Implement `tools/documents/`: OpenPyXL (Excel), Python-DOCX (Word), Python-PPTX (PowerPoint).
- [x] 9.4 Write and run `tests/verify_browser_media.py`.
- **Status**: ✅ Completed (Verified via tests/verify_browser_media.py with all suites passed)

### Step 9.5: Zero-Vision Universal Desktop Automation (`makima/tools/desktop/`) [HIGH PRIORITY]
- [x] 9.5.1 Desktop session attacher (`win32service.OpenDesktop` & `SetThreadDesktop` with STA isolation) to eliminate background window isolation.
- [x] 9.5.2 Microsoft UI Automation (UIA) tree walker: `inspect_app_ui()` returning compressed semantic control hierarchy.
- [x] 9.5.3 Native UIA Action Patterns: `click_ui_element()` (`InvokePattern`), `set_ui_text()` (`ValuePattern`), `read_ui_text()`, `send_keys_to_app()`.
- [x] 9.5.4 Win32 messaging fallback for legacy dialogs.
- [x] 9.5.5 Write and run `tests/verify_desktop_uia.py`.
- **Status**: ✅ Completed (Verified via tests/verify_desktop_uia.py with 4/4 passing suites in 0.57s)

---

## 🔵 Phase 3: Dual-Tier Memory & Self-Improving Skills

### Step 10: Dual-Tier Memory Engine (`makima/memory/`)
- [x] 10.1 Implement `state.py`: System prompt injection of `~/.makima/MEMORY.md` and `~/.makima/USER.md`.
- [x] 10.2 Implement `episodic.py`: Async SQLite WAL database via `aiosqlite` for conversation turns.
- [x] 10.3 Implement `vector_search.py`: `fastembed` + `sqlite-vec` on-device semantic search without PyTorch. ✅ DONE
- [x] 10.4 Write and run `tests/verify_memory.py` (store turn, FTS search, prompt injection test).
- **Status**: ✅ Completed (Verified via tests/verify_memory.py with 9 passing test suites)

### Step 11: Dynamic Markdown Skills Engine (`makima/skills/`)
- [x] 11.1 Implement `loader.py`: Dynamic scanner of `~/.makima/skills/**/*.md` with YAML frontmatter parsing.
- [x] 11.2 Implement `synthesizer.py`: `save_learned_skill()` tool allowing agent to write fresh markdown skills.
- [x] 11.3 Write and run `tests/verify_skills.py` (load sample skill, test agent skill synthesis).
- **Status**: ✅ Completed (Verified via tests/verify_skills.py with 5 passing test suites)

---

## 🟣 Phase 4: Multi-Platform Messaging Gateway

### Step 12: Gateway Daemon Core & Security (`makima/gateway/`)
- [x] 12.1 Implement `daemon.py`: Standalone long-running daemon runner with supervisor loop.
- [x] 12.2 Implement `security.py`: User allowlist checking and pairing code authorization.
- [x] 12.3 Implement `scheduler.py`: `apscheduler` integration for recurring cron routines and reminders.
- [x] 12.4 Write and run `tests/verify_gateway_core.py` (start daemon, test allowlist auth, scheduler, and pairing).
- **Status**: ✅ Completed (Verified via tests/verify_gateway_core.py with 4/4 passing suites)

### Step 13: Telegram & Discord Adapters (`makima/gateway/adapters/`)
- [x] 13.1 Implement `telegram.py`: `python-telegram-bot` with voice memo transcription, photos, commands.
- [x] 13.2 Implement `discord.py`: `discord.py` bot with slash commands and thread persistence.
- [x] 13.3 Write and run `tests/verify_adapters.py` (mock message loop).
- **Status**: ✅ Completed (Verified via tests/verify_adapters.py with 4 passing test suites in 2.6s)

### Step 14: WhatsApp Web & Email Adapters (`makima/gateway/adapters/`)
- [x] 14.1 Implement `whatsapp.py`: Baileys / QR Web Pair Bridge (linked-device without Meta API fees).
- [x] 14.2 Implement `email_daemon.py`: Async IMAP listener + SMTP reply dispatcher.
- [x] 14.3 Write and run `tests/verify_whatsapp_email.py`.
- **Status**: ✅ Completed (Verified via tests/verify_whatsapp_email.py with 5 passing test suites)

---

## 🟠 Phase 5: Voice & Multimodal Audio

### Step 15: Gemini 3.8 Live Bidirectional Audio (`makima/voice/gemini_live.py`)
- [x] 15.1 Implement full-duplex WebSocket stream using `google-genai` (16kHz PCM in -> 24kHz audio out).
- [x] 15.2 Implement native barge-in handling (cut off speaker on mic speech) and in-stream tool execution.
- [x] 15.3 Write and run `tests/verify_gemini_live.py`.
- **Status**: ✅ Completed (Verified via tests/verify_gemini_live.py with 5 passing test suites in 0.83s)

### Step 16: Hardware Audio I/O & Streaming Buffer (`makima/voice/audio_io.py`)
- [x] 16.1 Implement `audio_io.py`: Low-latency microphone capture and 24kHz PCM speaker stream via `sounddevice`.
- [x] 16.2 Implement `controller.py`: LiveVoiceController full-duplex session manager with real-time barge-in.
- [x] 16.3 Zero-TTS mandate strictly enforced (standalone TTS deprecated/removed per user directive).
- [x] 16.4 Verified live hardware device discovery and PCM stream playback.
- **Status**: ✅ Completed (Zero-TTS verified, Gemini 3.8 Live native audio integrated)

---

## 🔴 Phase 6: Interfaces & Final Polish

### Step 17: Rich Terminal CLI (`makima/cli/main.py`)
- [x] 17.1 Implement `makima chat` (interactive terminal chat with streaming and tool spinners).
- [x] 17.2 Implement `makima gateway run` (start background multi-platform daemon).
- [x] 17.3 Implement `makima tools list` (view active tools and schemas).
- [x] 17.4 Write and run `tests/verify_cli.py`.
- **Status**: ✅ Completed (Verified via tests/verify_cli.py with all 7 CLI suites passing)

### Step 18: FastAPI Server & Desktop UI (`makima/api/` & `makima/ui/`)
- [x] 18.1 Implement `app.py`: FastAPI server lifespan with health & telemetry (`/health`, `/api/status`, `/api/tools`, `/api/chat`).
- [x] 18.2 Implement `ws.py`: Real-time WebSocket streaming bridge for desktop UI (`/ws`).
- [x] 18.3 Connect React + Vite Desktop UI with tool status pills and canvas code viewer.
- [x] 18.4 Write and run `tests/verify_api.py`.
- **Status**: ✅ Completed (Verified via tests/verify_api.py with 6 passing test suites in 0.94s)

---

## 🚀 Phase 7: Engine Intelligence & Memory Integration

> **Goal**: Connect the subsystems built independently into one unified intelligent loop. Engine, episodic memory, vector search, and skills loader all exist but are NOT wired into each other at runtime yet.

### Step 19: Memory Wiring into HermesAgentEngine ⭐ HIGH PRIORITY
> **Why**: Engine currently has zero memory — each run starts from scratch. This wires dual-tier memory so Makima actually remembers across sessions.
- [x] 19.1 Inject `EpisodicMemory` into `HermesAgentEngine` — auto-store every turn (role, content, tool_calls) post-execution.
- [x] 19.2 Inject `VectorSearchEngine` — at session start, semantic search top-5 relevant past turns and inject as "Memory Context" block in system prompt.
- [x] 19.3 Inject `StateMemory` — auto-load `MEMORY.md` and `USER.md` facts into system prompt prefix.
- [x] 19.4 Propagate `session_id` through `HermesAgentEngine.run()` so all turns are grouped correctly in episodic store.
- [x] 19.5 Write and run `tests/verify_e2e.py` (multi-turn session with cross-run memory recall).
- **Status**: ✅ Completed (Verified via tests/verify_e2e.py)

### Step 20: Skills Auto-Injection into Engine Context ⭐ HIGH PRIORITY
> **Why**: Skills engine (Step 11) was built but never wired to the agent — it can't use its own learned skills.
- [x] 20.1 At engine startup, `SkillsLoader.scan()` loads all markdown skills from `~/.makima/skills/`.
- [x] 20.2 Matching skills (by keyword/tag match against user prompt) injected as "Active Skills" block in system prompt.
- [x] 20.3 `save_learned_skill` tool registered so agent can write new skills mid-conversation.
- [x] 20.4 Write and run `tests/verify_e2e.py` (skills injected into system prompt).
- **Status**: ✅ Completed (Verified via tests/verify_e2e.py)

### Step 21: Auto-Index Episodic Turns into Vector Store
> **Why**: VectorSearchEngine (Step 10.3) is standalone — needs to auto-index turns as they're stored so semantic recall works without manual calls.
- [x] 21.1 In `_persist_turns_background()` — after SQLite insert, index content in `VectorSearchEngine`.
- [x] 21.2 Strong reference held in `_background_tasks` set (prevent asyncio GC mid-execution).
- [x] 21.3 Turn auto-indexing verified in end-to-end integration loop.
- [x] 21.4 Write and run `tests/verify_e2e.py`.
- **Status**: ✅ Completed (Verified via tests/verify_e2e.py with doc_count verification)

### Step 22: Fast Web Search Tool (`makima/tools/web_search.py`)
> **Why**: Browser tools use Playwright (heavy). Most queries just need fast HTTP search — a lightweight web_search tool is completely missing from the tool registry.
- [x] 22.1 Implement `web_search(query, max_results=5)` using `httpx` + `BeautifulSoup4` (already installed) — returns `[{title, url, snippet}]`.
- [x] 22.2 Implement `fetch_page(url, extract_text=True)` — fast text extraction, no Playwright launch overhead.
- [x] 22.3 Register both as `@tool` entries — auto-discovered by ToolRegistry.
- [x] 22.4 Write and run `tests/verify_web_search.py`.
- **Status**: ✅ Completed (9/9 suites pass — live DuckDuckGo search confirmed working)

---

## 🏗️ Phase 8: Production Hardening & Packaging

> **Goal**: Close the gap between "all tests pass" and "actually boots and runs reliably as a real application."

### Step 23: Fix pytest Collection & Unified Test Runner
- [x] 23.1 Fix `test_run.py` broken import (`test_directory_clamping_and_traversal_blocking` → `test_directory_clamping`). ✅ DONE
- [x] 23.2 Add `tests/conftest.py` that adds project root to `sys.path` — `python -m pytest tests/ -q` now exits code 0. ✅ DONE
- [x] 23.3 Convert `verify_config.py`, `verify_tool_registry.py`, `verify_memory.py` into proper `pytest` test functions (`tests/test_smoke.py`). ✅ DONE
- [x] 23.4 `python -m pytest` exits code 0 with all 15 unit tests passing. ✅ DONE
- **Status**: ✅ Completed (Verified with 15/15 passing pytest tests)

### Step 24: `makima/core/telemetry.py` — Structured Runtime Observability
> **Why**: Zero runtime observability — no way to know what the engine is doing, which provider was picked, or how long tools took. Blind debugging in production.
- [x] 24.1 `StructuredTelemetry` — lightweight in-process event emitter (no Prometheus, no external service).
- [x] 24.2 Events: `engine.turn_start/end`, `provider.request/response`, `tool.execute/error`.
- [x] 24.3 Persist to `~/.makima/state/telemetry.jsonl` (append-only, daily rotation).
- [x] 24.4 Expose last-N events via `GET /api/telemetry` endpoint in FastAPI app.
- [x] 24.5 Write and run `tests/verify_telemetry.py`.
- **Status**: ✅ Completed (Verified via tests/verify_telemetry.py with 9 passing suites)

### Step 25: Fix `pyproject.toml` — Python Version Bug & Dependency Cleanup ⚠️ BUG
> **Why**: `requires-python = ">=3.11,<3.14"` but we're running Python 3.14.6 — would block pip install on our own machine.
- [x] 25.1 Fix `requires-python = ">=3.11"` (remove `<3.14` upper cap). ✅ DONE
- [x] 25.2 Remove `edge-tts` from core dependencies (Zero-TTS mandate — permanently banned). ✅ DONE
- [x] 25.3 Updated `fastembed>=0.8.0` and `sqlite-vec>=0.1.9` version pins. ✅ DONE
- [x] 25.4 Add `[project.scripts]` entry: `makima = "makima.cli.main:app"`. ✅ DONE
- **Status**: ✅ Completed

### Step 26: End-to-End Integration Test (`tests/verify_e2e.py`)
> **Why**: All verify_ scripts test modules in isolation. No test verifies the full chain: prompt → engine → tool call → memory store → response.
- [x] 26.1 Mock provider injected into `HermesAgentEngine`.
- [x] 26.2 Run 3-turn session: verify tool called, turns stored in EpisodicMemory, VectorSearch indexed them.
- [x] 26.3 Second engine run with same `session_id` — verify memory context recalled from first run.
- [x] 26.4 Ensure exit code 0.
- **Status**: ✅ Completed (Verified via tests/verify_e2e.py with 14 passing suites)

---

## 💎 Phase 9: Lean Desktop Capabilities (Library-First & Bloat-Free)

> **Mandate**: Zero custom wheels, zero overengineering. Use installed libraries and open-source packages directly.
> **Pruned/Excluded**: Obsidian Sync (permanently dropped per user request), 13-state emotion decay machine (model-native system prompt handles persona), mental state window-velocity sensor, static 23-rule CVE dictionary, and fake mock calendars.

### Step 27: Hermes-Style `cronjob_manage` Tool (`makima/tools/automation/cronjob.py`)
> **Why**: Scheduled reminders and recurring routines without custom polling loop or file-lock bugs.
- [x] 27.1 Implement `cronjob_manage(action, name, prompt, schedule, enabled=True)` using installed `apscheduler>=3.10.4`.
- [x] 27.2 Actions: `create`, `list`, `pause`, `resume`, `remove`, `run`.
- [x] 27.3 SQLite-backed job persistence across restarts with date, interval, and cron trigger support.
- [x] 27.4 Write and run `tests/verify_cronjob.py`.
- **Status**: ✅ Completed (Verified via tests/verify_cronjob.py with 10 suites / 27 tests passing)

### Step 28: Universal Document Ingestion via Microsoft MarkItDown (`makima/tools/documents/reader.py`)
> **Why**: Replaces 1,471 lines of fragile custom parsing glue code with Microsoft's battle-tested multi-format engine.
- [x] 28.1 Implement `read_document(file_path)` using `markitdown` (Microsoft) to convert PDF, DOCX, XLSX, PPTX, CSV, and HTML directly into clean, LLM-optimized Markdown.
- [x] 28.2 Graceful fallback to `pdfplumber` (already installed in `pyproject.toml`) if `markitdown` is optional.
- [x] 28.3 Write and run `tests/verify_markitdown.py`.
- **Status**: ✅ Completed (Verified via tests/verify_markitdown.py with 9 passing suites)

### Step 29: Instant Windows App Controller (`makima/tools/os/app_opener.py`)
> **Why**: Eliminates 400 lines of manual .lnk / registry searching by using fuzzy name matching and `os.startfile`.
- [x] 29.1 Implement `launch_application(name)` and `terminate_application(name)` using `AppOpener` / `os.startfile()`.
- [x] 29.2 Auto-detect Windows store apps, desktop executables, and registered protocol URIs (`spotify:`, `calc:`).
- [x] 29.3 Write and run `tests/verify_app_opener.py`.
- **Status**: ✅ Completed (Verified via tests/verify_app_opener.py with 5 passing suites)

### Step 30: Native Windows Desktop Toast Alerts (`makima/tools/os/notifications.py`)
> **Why**: Replaces fake JSON notification queues and slow PowerShell C# scripts with instant native Windows 10/11 Action Center alerts.
- [x] 30.1 Implement `show_desktop_notification(title, message, buttons=None, dialogue=None)` using `win11toast`.
- [x] 30.2 Support interactive actions (e.g. "Snooze", "Open") and wire into `cronjob_manage` reminder triggers.
- [x] 30.3 Write and run `tests/verify_notifications.py`.
- **Status**: ✅ Completed (Verified via tests/verify_notifications.py with 5 passing suites)

### Step 31: Fast Song & Media Playback Tool (`makima/tools/media/play_song.py`)
> **Why**: Instant music/video playback without API keys, quota limits, or heavy browser automation.
- [x] 31.1 Implement `play_song(query, platform="youtube")` using `youtube-search` / direct URL dispatch via `webbrowser.open()` and `os.startfile()`.
- [x] 31.2 Wire seamlessly with existing WinRT media transport controls (`control_media` play/pause/skip) and `pycaw` master volume.
- [x] 31.3 Write and run `tests/verify_media_player.py`.
- **Status**: ✅ Completed (Verified via tests/verify_media_player.py with 4 passing suites)

### Step 32: Full Interactive Desktop App Lifecycle Verification (`tests/verify_app_interactive_lifecycle.py`)
> **Why**: Proves that desktop automation isn't just launching and closing apps, but executing full in-app workflows (typing, live UI reading, saving to disk, clean termination).
- [x] 32.1 Prepare disk target document file.
- [x] 32.2 Launch application (`launch_app` / `launch_application`).
- [x] 32.3 Inspect control tree hierarchy via zero-vision Microsoft UI Automation (`inspect_app_ui`).
- [x] 32.4 Perform in-app interactive work: set text inside Edit control (`set_ui_text`).
- [x] 32.5 Verify live UI state: read back rendered text from live UI element (`read_ui_text`).
- [x] 32.6 Save work: trigger application Save command (`WM_COMMAND` / `send_keys_to_app`).
- [x] 32.7 Terminate application cleanly (`WM_CLOSE` + `terminate_process`).
- [x] 32.8 Assert on-disk persistence of saved text, send desktop notification (`show_desktop_notification`), and clean up scratch file.
- [x] 32.9 Add `test_interactive_app_lifecycle_smoke` to `tests/test_smoke.py`.
- **Status**: ✅ Completed (Verified via tests/verify_app_interactive_lifecycle.py with all 8 stages passed, and pytest 21/21 passed)

### Step 33: Direct Hardware-Grade Input Simulator (`makima/tools/desktop/input.py`)
> **Why**: Replaces deprecated `pyautogui` / `mouse_event` with native Win32 `SendInput` structures via `ctypes` (zero-dropped clicks in games & DirectInput).
- [x] 33.1 Implement `INPUT`, `MOUSEINPUT`, `KEYBDINPUT` structures and virtual key mapping.
- [x] 33.2 Implement `mouse_move`, `mouse_click`, `mouse_drag`, `mouse_scroll`, `get_cursor_position`.
- [x] 33.3 Implement `keyboard_type` (KEYEVENTF_UNICODE) and `keyboard_hotkey` chords.
- [x] 33.4 Write and run `tests/verify_desktop_input.py`.
- **Status**: ✅ Completed (Verified via tests/verify_desktop_input.py with all 3 test suites passing)

### Step 34: High-Performance Window & Screen Capture (`makima/tools/desktop/screen.py`)
> **Why**: Win32 `PrintWindow(PW_RENDERFULLCONTENT)` captures full high-DPI bitmaps of occluded/background windows with 0ms visual delay.
- [x] 34.1 Implement `capture_window(title_query, hwnd, save_path)` using Win32 GDI and Pillow.
- [x] 34.2 Implement `capture_screen(save_path)` with active window and desktop fallback.
- **Status**: ✅ Completed (Verified via tests/verify_som_vision.py)

### Step 35: Set-of-Marks (SoM) Visual Grounding Engine (`makima/tools/desktop/som.py`)
> **Why**: Solves coordinate hallucination by overlaying numbered pill badges (`#1`, `#2`, ...) on all interactive controls (Microsoft OmniParser / OSWorld style).
- [x] 35.1 Filter interactive controls (Button, Edit, MenuItem, TabItem, CheckBox) from UIA control tree.
- [x] 35.2 Translate screen coordinates to window bounds and render vibrant high-contrast badges via Pillow.
- [x] 35.3 Store badge-to-physical-coordinate mappings in `_LAST_SOM_CACHE`.
- [x] 35.4 Write and run `tests/verify_som_vision.py`.
- **Status**: ✅ Completed (Verified via tests/verify_som_vision.py with 14 marks generated and verified)

### Step 36: Unified SOTA `computer_use` Facade (`makima/tools/desktop/computer_use.py`)
> **Why**: Single standard entry point compatible with Astra, OSWorld, and Anthropic Computer Use APIs.
- [x] 36.1 Implement `computer_use(action, coordinate, mark_id, text, key, keys, button, clicks, direction)`.
- [x] 36.2 Support mark-based clicking (`click` with `mark_id`), physical coordinate clicking, Unicode typing, hotkeys, scroll, and screenshot.
- [x] 36.3 Add `test_computer_use_smoke` to `tests/test_smoke.py`.
- [x] 36.4 Write and run `tests/verify_computer_use.py`.
- **Status**: ✅ Completed (Verified via tests/verify_computer_use.py with all 8 stages passed, and pytest 22/22 passed)

### Step 37: Hermes-Style Autonomous User Preference & Memory Tools (`makima/tools/memory.py`)
> **Why**: Enables the AI model to autonomously learn, persist, and recall user preferences and knowledge facts directly into Markdown state (`USER.md` and `MEMORY.md`) with zero bloat.
- [x] 37.1 Implement `@tool remember_user_preference(preference)` and `@tool forget_user_preference(search_text)`.
- [x] 37.2 Implement `@tool remember_fact(fact, category)` and `@tool forget_fact(search_text)`.
- [x] 37.3 Implement `@tool get_user_profile()` and `@tool get_memory_facts()`.
- [x] 37.4 Add `delete_user_preference` method to `StateMemory` in `makima/memory/state.py`.
- [x] 37.5 Export memory tools in `makima/tools/__init__.py` and auto-discover via `ToolRegistry`.
- [x] 37.6 Add `test_preference_memory_tools_smoke` to `tests/test_smoke.py`.
- [x] 37.7 Write and run `tests/verify_preference_memory.py`.
- **Status**: ✅ Completed (Verified via tests/verify_preference_memory.py with all 8 stages passed, and pytest 23/23 passed)

### Step 38: SOTA Interactive Visible Browser Controller (`makima/tools/browser/automation.py`)
> **Why**: Upgrades read-only single-shot Playwright into a persistent interactive browser agent following the `browser-use` indexed-element pattern with visible desktop display (`headless=False`).
- [x] 38.1 Implement persistent singleton `BrowserController` with lifecycle locks and dynamic Chromium launcher.
- [x] 38.2 Implement in-page DOM distillation extracting numbered interactive elements (`[1]`, `[2]`, ...) with center coordinates and element metadata.
- [x] 38.3 Implement unified `@tool browser_interact(action, url, index, selector, text, key, scroll_y, headless)` supporting `navigate`, `get_elements`, `click`, `type`, `press_key`, `scroll`, `screenshot`, `get_text`, and `close`.
- [x] 38.4 Support `file://` protocols alongside `http://` and `https://` for local test isolation and web apps.
- [x] 38.5 Export `browser_interact`, `BrowserController`, `get_browser_controller` in `makima/tools/browser/__init__.py`.
- [x] 38.6 Add `test_interactive_browser_smoke` to `tests/test_smoke.py`.
- [x] 38.7 Write and run `tests/verify_interactive_browser.py`.
- **Status**: ✅ Completed (Verified via tests/verify_interactive_browser.py with all 7 stages passed, and pytest 17/17 passed)

### Step 39: Autonomous Implicit User Preference & Habit Learner (`makima/memory/reflection.py`)
> **Why**: Enables Makima to autonomously observe user feedback, corrections ("No, don't use Chrome, use Brave instead"), and habits post-turn without requiring manual user commands, persisting them to `~/.makima/USER.md` with zero user latency.
- [x] 39.1 Implement `ImplicitPreferenceLearner` with direct heuristic extraction and LLM reflection fallback.
- [x] 39.2 Implement transient command filtering (skip temporary actions like 'click button 2', 'read test.py').
- [x] 39.3 Implement deduplication check (`is_already_known`) against existing `USER.md` entries.
- [x] 39.4 Wire post-turn background reflection hook into `HermesAgentEngine.run()`.
- [x] 39.5 Export `ImplicitPreferenceLearner` in `makima/memory/__init__.py`.
- [x] 39.6 Add `test_implicit_preference_learner_smoke` to `tests/test_smoke.py`.
- [x] 39.7 Write and run `tests/verify_implicit_preferences.py`.
- **Status**: ✅ Completed (Verified via tests/verify_implicit_preferences.py with all 5 stages passed, and pytest 18/18 passed in 11.27s)

### Step 40: Makima-owned OSWorld / Daytona Benchmark Harness
- [x] 40.1 Add OSWorld-shaped `MakimaOSWorldAgent` entrypoint with Makima system identity.
- [x] 40.2 Keep provider model attribution separate as `reasoning_backend`.
- [x] 40.3 Add lazy Daytona runtime wrapper and benchmark configuration.
- [x] 40.4 Add deterministic contract tests for Makima tool execution and attribution.
- **Status**: ✅ Harness contract verified with `tests/test_osworld_makima.py` (2 passed). A real OSWorld score still requires the official OSWorld evaluator plus a configured Daytona/GUI bridge.




