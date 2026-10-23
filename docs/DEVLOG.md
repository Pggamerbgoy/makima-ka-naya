# 📝 Makima v2 — Engineering Decision & Architecture Log (DEVLOG)

> **Purpose**: Formal engineering record of major architectural decisions, evaluated tradeoffs, rejected alternatives, and resolved platform-specific edge cases throughout the development of Makima v2.

## 📅 2026-10-23

### Entry 16: Comprehensive Subsystem Audit, HTTP Connection Pooling, Fault-Tolerant Memory & Zero-Hardcoding Guarantees
- **Context**: The user requested a full-codebase adversarial audit and structural hardening across Makima's Core, Sentinel, Memory, Gateway, and Tools subsystems to eradicate hardcoded endpoints, connection overhead, memory deadlocks, and silent failure modes before publishing the repository.
- **Decisions & Tradeoffs**:
  1. **HTTP Connection Pooling (`makima/core/http_pool.py`)**:
     - *Issue*: Ad-hoc `httpx.AsyncClient()` instantiations across search tools and REST adapters incurred TCP handshake overhead and socket exhaustion under high concurrency.
     - *Solution*: Implemented singleton `HTTPPool` bound to active event loops with keepalive limits (`settings.http_max_keepalive`, `settings.http_max_connections`) and request timeouts dynamically derived from `MakimaSettings`.
  2. **Fault-Tolerant Memory Engine (`reflection.py`, `state.py`, `vector_search.py`, `episodic.py`)**:
     - *Reflection Lock Safety*: Replaced shared module lock with dynamic event-loop binding to prevent cross-thread `RuntimeError` during asynchronous reflection.
     - *Atomic Profile Writes*: Added `_atomic_write` utilizing temporary files (`.tmp`) and atomic filesystem replacement to prevent corrupted or zero-byte `USER.md` on sudden crashes.
     - *FTS5 Reserved Word Filtering*: Stripped boolean operator collision tokens (`AND`, `OR`, `NOT`, `NEAR`) from raw search queries to ensure 100% SQLite FTS5 query stability.
     - *LRU Caching & Dynamic Vectors*: Added 1,000-entry LRU embedding cache in `VectorSearchEngine` and dynamic dimension resolution from `configs/settings.yaml`.
  3. **Gateway Supervisor Resilience (`makima/gateway/daemon.py` & adapters)**:
     - Isolated platform adapters (`telegram`, `discord`, `whatsapp`, `email`) in supervised initialization handlers with exponential backoff on network disconnections.
  4. **Adversarial Context Scaling (`makima/core/context.py`)**:
     - Implemented dynamic budget scaling for `_clamp_large_message` ensuring small-budget contexts (e.g. 8k LLaMA) clamp oversized payloads (<2200 chars) while large-budget contexts (Gemini 1M, Qwen 128k) preserve full operational trace.
- **Verification & Outcome**:
  - `tests/verify_sentinel.py`: All 8 stages passed with exit code 0.
  - `tests/verify_memory.py` & `tests/verify_vector_search.py`: Passed 100% (7/7).
  - `tests/verify_engine.py` & `tests/verify_engine_memory.py`: Passed 100% (8/8).
  - `tests/test_tier5_adversarial_hardening.py`: 21/21 passed in 11.72s.
  - `tests/verify_gateway_core.py` & `tests/verify_whatsapp_email.py`: Passed 100%.

---

## 📅 2026-10-17

### Entry 15: Claude-Style Live & Collapsible Execution Stepper on Chat UI
- **Context**: The user requested Claude-style step transparency ("makima ke steps bhi show karo ui pe pls jisse pta chale user ko ki makima kaha stop ho rhi and kaha pahochi hai just like claude"). Previously, users only saw a static pulsing "Makima is reasoning & synthesizing..." badge during execution, and all tool execution traces vanished once generation finished, leaving no record of what tools were executed, what parameters were passed, where Makima stopped, or why a step failed.
- **Decisions & Tradeoffs**:
  1. **Dual-Lifecycle Stepper (Live vs Collapsed Trace)**:
     - *Live Stepper (`message.pending === true`)*: Replaced the static thinking block with a real-time reactive execution timeline. Displays the currently running step with an active spinner, dynamic stage notice (e.g. `Browsing live web (navigate to https://www.miruro.ru)...`), and previously completed steps with green checks or failure badges.
     - *Completed Accordion (`message.pending === false`)*: Collapses into a clean, modern Claude-style accordion header (`▼ Thought & executed N steps [browser_interact] 1.2s`). If any step failed or encountered an error, the accordion automatically expands by default to immediately highlight the exact failed step and error reason to the user.
  2. **Detailed Parameter & Output Inspection**:
     - Each step item contains collapsible parameter drawer (`Parameters: formatted JSON`) and output preview (`Output: formatted text/JSON truncated safely`), allowing deep inspection without visual clutter.
  3. **Full End-to-End WebSocket & Session Persistence**:
     - Updated `makima/api/ws.py` to record structured `executed_steps` in real time during `ws_tool_executor` and `on_turn_end`.
     - Attached `steps` in `send({"type": "message", "steps": ...})`, `send({"type": "task_cancelled", ...})`, and `send({"type": "error", ...})`.
     - Saved `steps` into SQLite `messages.metadata["steps"]`, ensuring that historical sessions loaded via `api.getSession()` retain the full execution accordion across page refreshes and session switching.
- **Verification & Outcome**:
  - `tsc -b && vite build` passed cleanly with exit code 0 (`dist/` production assets generated).
  - All core engine test suites (`tests/verify_engine.py` and `tests/verify_engine_memory.py`) pass 100%.

### Entry 14: System Prompt Streamlining & Runtime Engine Protocol Alignment
- **Context**: An honest behavioral and code audit of `HermesAgentEngine.DEFAULT_SYSTEM_PROMPT` revealed token bloat from 5 redundant sections (`<capabilities>`, `<todo_rules>`, `<writing_rules>`, `<multi_agent_rules>`, `<task_completion_checklist>`), and missing instructions for 3 real engine runtime communication envelopes (`[TOOL_FAILED: name]`, `[CONTEXT COMPRESSED: N turns omitted]`, `[SYSTEM NOTICE: Loop detected]`).
- **Decisions & Tradeoffs**:
  1. **Zero-Duplication Pruning**: Removed `<capabilities>` because tools are dynamically declared in `tool_schemas` (OpenAI/Gemini function calling format). Removed `<todo_rules>`, `<writing_rules>`, and `<task_completion_checklist>` which duplicated `<agent_loop>`, `<language_settings>`, and `<coding_rules>`. Folded `<multi_agent_rules>` into a single sentence inside `<identity>`.
  2. **Preserving Critical Edge Cases**: Retained shell-escaping avoidance and large scrape scratch-file persistence in a tight 3-line `<file_rules>`, and moved multi-session task state persistence into `<memory_rules>`.
  3. **Explicit Runtime Engine Contracts**:
     - Added `[TOOL_FAILED: <tool_name>] <ErrorType>: <message>` protocol in `<tool_use_rules>`.
     - Added `[CONTEXT COMPRESSED: ...]` protocol in `<cross_turn_context>` ensuring condensed summaries are treated as ground truth without reprompting the user.
     - Added `[SYSTEM NOTICE: Loop detected — ...]` and `[SYSTEM DIRECTIVE]` protocol in `<agent_loop>` to trigger immediate stop and final synthesis.
  4. **Platform-Conditioned Suggestions**: Conditioned the ````suggestions ... ```` block in `<response_style>` to conversational chat / React web UI, omitting it for voice mode and 1-line acknowledgments to save tokens.
- **Verification & Outcome**: `DEFAULT_SYSTEM_PROMPT` reduced from 610 lines to 532 lines (**-78 lines, -963 tokens saved per turn**). All 8 core engine tests in `tests/verify_engine.py` and all 4 memory tests in `tests/verify_engine_memory.py` pass with 100% success.

---

## 📅 2026-09-30

### Entry 13: Autonomous Implicit User Preference & Habit Learning (Step 39)
- **Context**: Explicit memory tools (`remember_user_preference`) require the user to explicitly command the AI to save preferences. In practice, users casually provide feedback or corrections (e.g. "No, don't use Chrome, use Brave instead", "From now on, speak in concise bullets", "Always run tests before committing"). Without implicit extraction, this knowledge is lost between sessions. User chose this capability over tool intent masking.
- **Decisions & Tradeoffs**:
  1. **Two-Tier Extraction Pipeline**:
     - *Tier 1: Fast Heuristic Extraction (0ms, 0 API calls)*: Deterministic regex parsing for direct preferences ("I prefer X"), behavioral directives ("Always do X", "Never do X"), temporal shifts ("From now on, do X"), identity markers ("My name is X"), and action corrections ("No, don't use X, use Y").
     - *Tier 2: Asynchronous LLM Reflection Fallback*: If heuristics don't match but correction signals ("no", "nahi", "wrong", "instead", "actually", "mat karo") are present, runs a tiny, fast background reflection prompt to classify persistent preferences.
  2. **Transient Command Filtering**: One-off instructions ("click button 2", "read test.py", "kill process 1024") are filtered out to prevent cluttering `USER.md` with ephemeral commands.
  3. **Deduplication Engine**: Candidate preferences are checked against current `USER.md` content using both exact substring matching and token overlap (>75%) to prevent redundant duplicate bullet points.
  4. **Post-Turn Background Lifecycle**: Hooked into `HermesAgentEngine.run()` as an asynchronous fire-and-forget task (holding a strong reference in `self._background_tasks`). Operates with zero latency penalty to the user response.
- **Verification & Outcome**: `tests/verify_implicit_preferences.py` passed all 5 stages. Added `test_implicit_preference_learner_smoke` to `tests/test_smoke.py`, with 18/18 pytest tests passing in 11.27s.

### Entry 10: Bloat Pruning & Library-First Ecosystem Integration (Phase 9)
- **Context**: The full audit of Makima v1 revealed numerous legacy features (Obsidian sync, 13-state emotion decay machine, mental state window-velocity counters, fake calendar/notification mocks, static 23-rule CVE dictionary). User explicitly mandated: *"jo list di hai usme se wo sab hta dena jiski need na lage ok and obsidian waale ko khas kar"* and to research open-source libraries across the ecosystem so we never hand-roll custom wheels.
- **Decisions & Tradeoffs**:
  1. **Permanent Pruning of Obsidian Sync**: Dropped `obsidian_sync.py`. Makima v2's primary source of truth is `aiosqlite` + `sqlite-vec` on-device memory.
  2. **Model-Native Persona over 13-Emotion Decay Machine**: Removed 569 lines of manual emotion mathematics. LLM system instructions natively handle Hinglish feminine inflection, devotion, and BLUF (Bottom Line Up Front) response discipline.
  3. **Universal Document Ingestion via Microsoft MarkItDown**: Replaced 1,471 lines of multi-library custom parsing glue code with Microsoft's official `markitdown` (`pip install markitdown`). Normalizes PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, JSON, and HTML directly into clean Markdown optimized for LLMs.
  4. **Instant Windows App Control via AppOpener / os.startfile**: Replaced 400 lines of SQLite FTS5 registry/shortcut scrapers with `AppOpener` + Windows `os.startfile`. Launches and closes apps via fuzzy matching without manual path knowledge.
  5. **Native Desktop Alerts via win11toast**: Replaced fake JSON notification queues and 400ms PowerShell C# scripts with `win11toast` (native Windows 10/11 Action Center alerts with interactive buttons).
  6. **Scheduled Reminders & Cron via APScheduler**: Modeled tool interface after Nous Research's `cronjob_manage` in `hermes-agent`, backed by installed `apscheduler>=3.10.4`. Supports date, interval, and cron triggers with SQLite persistence, avoiding Hermes' raw `.tick.lock` thread starvation issues.
  7. **Music & Song Playback via youtube-search + WinRT**: Direct query resolution via `youtube-search` / direct URL dispatch without requiring YouTube Data API v3 keys or quota limits, integrating with existing `winrt.windows.media.control` transport tools.
- **Outcome**: Documented in `TODO.md` as Steps 27–31 under Phase 9. All 15 existing pytest tests pass.

---

### Entry 9: Engine Intelligence Wiring, Runtime Observability & E2E Integration (Phases 7 & 8)
- **Context**: The individual subsystems (engine, dual-tier memory, skills loader, telemetry, tools) existed in isolation. For true autonomous operation, they needed unified runtime wiring, automated context enrichment, and full-chain verification.
- **Decision**:
  - **Memory & Skills Auto-Injection**: `HermesAgentEngine.run()` pre-processes the system prompt by calling `StateMemory.format_prompt_injection()`, `VectorSearchEngine.search()` (KNN semantic recall), and `SkillsLoader.search_skills()`.
  - **Background Persistence & Auto-Indexing**: Completed turns are asynchronously saved to `EpisodicMemory` (aiosqlite WAL) and embedded via `fastembed` into `VectorSearchEngine` in a background task (retaining a strong reference to prevent GC).
  - **Fast Web Search**: Lightweight `@tool` implementations (`web_search` and `fetch_page`) using `httpx` + `BeautifulSoup4` bypassing Playwright browser overhead for informational queries.
  - **Structured Telemetry**: In-process event emitter logging to daily-rotated `telemetry_YYYY-MM-DD.jsonl` files and an in-memory ring buffer exposed via `GET /api/telemetry`.
  - **Pytest Native Suite**: Created `tests/conftest.py` and `tests/test_smoke.py` enabling standard `python -m pytest` test runs.
  - **Full E2E Verification**: `tests/verify_e2e.py` exercises the complete multi-tier flow across all 6 subsystems simultaneously with 14/14 passing checks.
  - **Architecture Documentation**: Documented the full data flow and function calling hierarchy in `docs/DATA_FLOW.md`.
- **Outcome**: All 26 steps in `TODO.md` completed. 25/25 verification suites pass. 15/15 pytest tests pass.

---

## 📅 2026-09-29

### Entry 8: On-Device Semantic Vector Search — fastembed + sqlite-vec (Step 10.3)
- **Context**: Episodic memory (Step 10.2) already handles keyword search via FTS5, but FTS5 is lexical — it can't find "coroutine" when the user says "async task scheduling". A semantic layer is needed for relevant memory recall.
- **Decision**: `VectorSearchEngine` in `makima/memory/vector_search.py` using:
  - `fastembed 0.8.0` (ONNX Runtime, zero PyTorch dependency) — multilingual MiniLM-L12-v2 model (~45MB, downloaded once to fastembed cache).
  - `sqlite-vec 0.1.9` — sqlite3 extension providing `vec0` virtual table for KNN cosine search directly inside SQLite.
  - Separate DB file (`vector_store.db`) from episodic `history.db` to avoid WAL-mode conflicts between two different write workloads.
  - `asyncio.to_thread()` wraps synchronous fastembed embed calls to avoid blocking the event loop.
- **Graceful Degradation**: If `sqlite-vec` extension fails to load (e.g. missing C extension build), falls back to pure-Python brute-force cosine similarity over an in-memory list. No crash, no silent failure.
- **Alternatives Rejected**:
  - ChromaDB — heavyweight, spawns a separate subprocess, overkill for on-device use.
  - FAISS — requires C++ native build or GPU; fragile on Windows without conda.
  - PyTorch SentenceTransformers — too heavy (>500MB) for an always-on desktop assistant.
- **Test Result**: 7/7 suites pass including semantic search returning Python-related doc above food doc for query "async python coroutines".

---


### Entry 1: Ground-Up Rebuild via Nous Research Hermes Agent Pattern
- **Context**: Makima v1 suffered from tight coupling, 4,300-line monolithic files (`system_tools.py`), fragile subprocess invocations, and duplicate tool registries.
- **Decision**: Rebuild Makima completely in `makima_v2/` inspired by the `nousresearch/hermes-agent` architectural pattern:
  - Autonomous while-loop engine with decoupled provider routing.
  - Dynamic tool auto-discovery using Python type introspection and Pydantic v2.
  - Middle-turn context compression preserving goal context and tail history.
  - Dual-tier memory isolating human-inspectable state from relational episodic turns.
- **Alternatives Considered & Rejected**: Refactoring Makima v1 in-place was rejected because technical debt and circular imports across `apps/brain/` would require dozens of backward-compatibility shims.

---

### Entry 2: Zero-Cost Pareto Frontier Router
- **Context**: The assistant must be capable of running continuously without incurring API fees or blocking when individual provider limits are reached.
- **Decision**: Implemented `ParetoRouter` in `makima/provider/router.py`:
  - Dynamically probes localhost:11434 for active Ollama models (e.g. `qwen2.5-coder:7b`) and checks environment variables for free-tier keys (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`).
  - Maintains task-specific cascades (`fast_chat`, `code`, `deep_reasoning`, `offline`).
  - Implements multi-criteria candidate sorting prioritizing free and offline backends with EWMA latency scoring ($\alpha = 0.25$).
  - Integrates 3-state circuit breakers with randomized cooldown jitter to prevent thundering herd problems.

---

### Entry 3: Zero-Vision Desktop UI Automation via Microsoft UIA
- **Context**: The user mandated that the assistant must operate Windows software without capturing screenshots or using vision models due to latency, compute cost, and prompt token bloat.
- **Decision**: Built `makima/tools/desktop/uia.py` using `pywinauto` with `backend="uia"` and Win32 IPC:
  - **Thread Desktop Attacher**: Background agent threads on Windows run in isolated desktop stations where standard window enumeration returns empty lists. We implemented a dedicated worker thread pool that attaches to the interactive desktop (`win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL).SetThreadDesktop()`) before initializing COM Single-Threaded Apartment (`pythoncom.CoInitialize()`).
  - **Semantic Hierarchy**: Extracts structured control trees (`Button`, `Edit`, `MenuItem`, `TabItem`) in <500 tokens.
  - **Native Action Patterns**: Executes clicks via UIA `InvokePattern` and text input via `ValuePattern`.
- **Result**: Sub-second app inspection and interaction (0.57s execution time in verification tests).

---

### Entry 4: Native Gemini 3.8 Live Voice & Zero-TTS Mandate
- **Context**: User explicitly instructed: *"USE THE GEMINI 3.8 VOICE AND NO TTS"*.
- **Decision**:
  - Deprecated and removed standalone TTS modules (`edge_tts_synth.py`) and tools (`speak_text`).
  - Implemented `GeminiLiveSession` using `google-genai` SDK (`client.aio.live.connect`) over a full-duplex WebSocket stream with `types.Modality.AUDIO` response modality.
  - Model natively generates 24kHz PCM audio frames.
  - Implemented `LiveVoiceController` with real-time microphone RMS volume monitoring for instant barge-in: when user starts speaking while Gemini is talking, `AudioIO.stop_playback()` is immediately called.
  - Connected `ToolRegistry` function declarations directly to the live stream for in-stream tool execution mid-speech.

---

### Entry 5: Windows 10/11 ConPTY Non-Blocking Timeout Resolution
- **Context**: Windows 10 build 19045 and Windows 11 ConPTY streams block indefinitely on read operations when no interactive console window is attached.
- **Decision**:
  - Configured `conpty.py` to default to `winpty.Backend.WinPTY`.
  - Configured `self._pty.fileobj.settimeout(0.5)` and explicitly caught `(TimeoutError, socket.timeout)` exceptions during stream reads.
  - Allowed both non-blocking polling and interactive terminal command execution.

---

### Entry 6: Multi-Platform Gateway Security & Pairing Codes
- **Context**: Running multi-platform messaging daemons (Telegram, Discord, WhatsApp, Email) exposes the agent to unauthorized commands if access is unauthenticated.
- **Decision**:
  - Implemented `GatewaySecurityManager` with an authorization allowlist.
  - Added ephemeral 6-character pairing codes (`MK-XXXX`) with 15-minute TTL.
  - Users on any platform can pair by sending `/pair <CODE>` or `!pair <CODE>`. Upon verification, the user ID is permanently persisted to disk.

---

### Entry 7: Windows Console CP1252 Character Encoding Safety
- **Context**: Standard Windows command prompts and PowerShell terminals running on code page 1252 crash with `UnicodeEncodeError: 'charmap' codec can't encode character` when encountering Unicode checkmarks (`✓`), crossmarks (`✗`), or tree characters (`└─`).
- **Decision**:
  - Configured stream reconfiguration to UTF-8 in `makima/cli/main.py`.
  - Replaced ambiguous Unicode glyphs with ASCII/terminal-safe indicators (`[READY]`, `[NO KEY]`, `[OK]`, `[ACTIVE]`, `|-`, `->`).
  - Ensured 100% crash-free execution in all Windows shells.

---

### Entry 8: Interactive Desktop App Lifecycle & Zero-Vision UIA Thread Isolation Fix
- **Context**: The user required a complete, end-to-end interactive desktop application test where an app is not merely opened and closed, but interactive work is performed inside it (typing/setting content), verified via the live UI, saved directly to disk, and cleanly terminated.
- **Root Cause & Fixes**:
  1. **Thread Desktop Isolation**: Calling `win32service.OpenDesktop("default").SetThreadDesktop()` inside worker threads in `_desktop_executor` caused Windows to isolate the worker thread, causing `EnumDesktopWindows` and `_find_target_window` to return 0 active windows. Removing `SetThreadDesktop` while keeping STA `pythoncom.CoInitialize()` restored instant top-level window discovery.
  2. **UIA Text Extraction**: `child.window_text()` on Edit controls returned the accessible name (e.g. `'Text Editor'`), whereas `child.get_value()` and `legacy_properties().get('Value')` contain the actual user content. Enhanced `read_ui_text` to extract both.
  3. **Foreground Lock Guard**: Wrapped `win32gui.SetForegroundWindow` in a soft-catch block and provided a window-level fallback in `send_keys_to_app`.
  4. **Direct Win32 Command Saving**: Integrated Win32 `WM_COMMAND (ID 3)` message dispatch for 100% reliable programmatic saving without requiring foreground window focus.
- **Verification**:
  - Created and executed `tests/verify_app_interactive_lifecycle.py`: launched Notepad with target file, inspected UI hierarchy without screenshots, modified text via UIA, read back live text, saved to disk, cleanly terminated app, verified saved content on disk, and showed desktop notification.
  - Added `test_interactive_app_lifecycle_smoke` to `tests/test_smoke.py`.
  - All 21 tests passed cleanly under `pytest` in 13.77s.

---

### Entry 9: Astra-Grade Hybrid PC Control (SendInput Hardware Simulator, Set-of-Marks Grounding & Unified computer_use)
- **Context**: The user requested full, autonomous PC control matching SOTA models like GPT-6 Astra (which scored ~72.6% on OSWorld 2.0) and Microsoft UFO².
- **Architecture & Decision**:
  - Adopted the winning SOTA **Dual-Perception Hybrid** architecture:
    1. **Direct Hardware-Grade SendInput (`makima/tools/desktop/input.py`)**:
       - Defined native Win32 `INPUT`, `MOUSEINPUT`, `KEYBDINPUT` C structures via `ctypes`.
       - Native Unicode typing (`KEYEVENTF_UNICODE`) supporting all international characters, emojis, and symbols.
       - Built-in UIPI / background process fallback to `mouse_event` / `keybd_event` and targeted window routing to prevent Access Denied drops.
    2. **High-Performance Window & Screen Capture (`makima/tools/desktop/screen.py`)**:
       - Implemented Win32 `PrintWindow(PW_RENDERFULLCONTENT)` bitmap capture directly to PIL, capturing occluded and background windows with 0ms visual delay.
    3. **Set-of-Marks (SoM) Visual Grounding Engine (`makima/tools/desktop/som.py`)**:
       - Combines UIA bounding boxes with Pillow drawing to overlay high-contrast numbered badges (`#1`, `#2`, ...) on all interactive controls.
       - Caches mark-to-physical-coordinate mappings in `_LAST_SOM_CACHE` so any Vision LLM can target elements by badge ID.
    4. **Unified SOTA `computer_use` Facade (`makima/tools/desktop/computer_use.py`)**:
       - Unified Anthropic/OSWorld-compatible interface supporting `click`, `double_click`, `right_click`, `mouse_move`, `drag`, `type`, `key`, `hotkey`, `scroll`, `screenshot`, `som`, and `cursor_position`.
- **Verification**:
  - `tests/verify_desktop_input.py`: Passed (cursor position, mouse move, single/double click, scroll, drag, Unicode typing, hotkey).
  - `tests/verify_som_vision.py`: Passed (window capture, screen capture, 14 Set-of-Marks tags generated on live window).
  - `tests/verify_computer_use.py`: Passed (end-to-end Astra action suite against live application).
  - `tests/test_smoke.py`: All 22 tests passing in 14.92s.

---

### Step 37: Hermes-Style Autonomous User Preference & Memory Tools (2026-09-30)
- **Challenge**:
  - Makima v1 contained a 1,128-line heuristic preference engine that relied on brittle regexes and sliding-window frequency tables to guess user preferences.
  - Makima v2's Hermes-style architecture already featured `StateMemory` (`USER.md` and `MEMORY.md`), but lacked exposed `@tool`s for the AI model to autonomously record and manage preferences.
- **Architectural Solution**:
  - Pure library-first and zero-bloat design delegating directly to `StateMemory`:
    1. **`remember_user_preference(preference)`**: Autonomously records user habits, instructions, and preferences directly into `~/.makima/USER.md`.
    2. **`remember_fact(fact, category)`**: Autonomously records long-term project and system facts into categorized sections of `~/.makima/MEMORY.md`.
    3. **`forget_user_preference(search_text)`** & **`forget_fact(search_text)`**: Safe deletion tools for outdated preferences or facts.
    4. **`get_user_profile()`** & **`get_memory_facts()`**: Inspection tools for active profile and facts list.
  - Added symmetric `delete_user_preference` method to `StateMemory`.
  - Exported in `makima.tools` for instant dynamic discovery by `ToolRegistry`.
- **Verification**:
  - `tests/verify_preference_memory.py`: All 8 stages passed (tool discovery, persistence to `USER.md`, `MEMORY.md`, dynamic prompt injection, deletion, edge cases).
  - `tests/test_smoke.py`: Added `test_preference_memory_tools_smoke`.
  - Pytest full runner: **23/23 tests passing with Exit Code 0**.

---

### Step 38: SOTA Interactive Visible Browser Controller (2026-09-30)
- **Challenge**:
  - Makima v2's browser capabilities were limited to single-shot headless text extraction (`browse_page`).
  - There was no persistent browser session, no ability to interactively click, type, or scroll, and `headless=True` violated the visible desktop interaction mandate.
- **Architectural Solution**:
  - Implemented persistent async `BrowserController` (`makima/tools/browser/automation.py`) adopting the industry-standard `browser-use` indexed-element grounding pattern:
    1. **Visible Chromium Display (`headless=False`)**: Window renders live on user's desktop with anti-detection evasions (`--disable-blink-features=AutomationControlled`).
    2. **DOM Distillation & Element Grounding**: Injected JavaScript extracts visible, interactive elements (`button`, `a`, `input`, `select`, `textarea`) and assigns 1-based index numbers `[1]`, `[2]`, ... with center viewport coordinates and labels.
    3. **Unified `browser_interact` Tool**: Supports `navigate`, `get_elements`, `click` (via physical center coordinates or selector), `type` (with optional Enter keypress), `press_key`, `scroll`, `screenshot`, `get_text`, and `close`.
    4. **Universal Protocol Support**: Handles `http://`, `https://`, and `file://` protocols.
  - Zero heavy third-party dependencies added; built entirely on top of installed `playwright 1.61.0`.
- **Verification**:
  - `tests/verify_interactive_browser.py`: All 7 stages passed (ToolRegistry discovery, navigation, element distillation, typing, clicking with DOM state assertion, scrolling, screenshot, clean session close).
  - `tests/test_smoke.py`: Added `test_interactive_browser_smoke`.
  - Full pytest runner: **17/17 test suites passing in 11.36s with Exit Code 0**.

---

## 📅 2026-10-01

### Entry 14: Windows Interactive Desktop Station Attacher & 10s End-to-End Multimodal Control Benchmark
- **Context & Bug Discovery**:
  - When background worker threads in `_desktop_executor` attempted to invoke Microsoft UI Automation (`pywinauto.Application(backend="uia").connect(handle=...)`) on modern Windows 10/11 UWP applications (e.g. `Calculator`, `Settings`), `pywinauto` threw `RuntimeError: Invalid handle ... passed to connect()`.
  - Root cause investigation revealed Win32 station isolation: background threads created in worker pools do not automatically inherit the interactive user desktop (`default`). Consequently, `win32gui.IsWindow(handle)` returned `0` inside pywinauto, failing handle validation.
- **Architectural Solution**:
  - Added `_init_desktop_thread()` in `makima/tools/desktop/uia.py` passed as `initializer` to `_desktop_executor`:
    ```python
    def _init_desktop_thread() -> None:
        try:
            desk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
            desk.SetThreadDesktop()
        except Exception as exc:
            logger.debug("Desktop thread attachment notice: %s", exc)
    ```
  - Crucial Win32 order invariant: `SetThreadDesktop` must execute *before* `pythoncom.CoInitialize()` on clean worker threads, otherwise Windows rejects desktop station switching with `Error 170 (The requested resource is in use)`.
- **Performance Benchmarks & Optimization**:
  - **Zero-Vision UIA Latency**: Measured pure programmatic UIA execution on Calculator (8 operations: clear + 4096 * 6 = 24576 + readback). Total execution took **342.6 ms (~42.8 ms per operation)**.
  - **Continuous Multi-Stage E2E Workflow**: Designed and executed an end-to-end test chaining 6 capabilities (Hardware Telemetry + Calculator UIA + Notepad SendInput typing + Settings Set-of-Marks visual grounding + WinRT Toast Notification).
  - Replaced rigid blind sleeps with active window handle polling (`_wait_for_window()`, 100ms interval). Total runtime dropped from 23s down to **10.04 seconds** with 100% pass rate.

---

### Entry 15: SOTA Desktop UX Enhancement Roadmap & Proactive Ambient Autopilot
- **Context**:
  - Analysis of Makima v1 (`chat_ui`, `native_overlay`) and modern SOTA desktop agents (Google Astra, OpenAI Operator, Claude Desktop) revealed opportunities to evolve Makima from a backend CLI agent into an effortless, ambient desktop companion.
- **Architectural UX Roadmap**:
  1. **Global Floating HUD / Spotlight Bar (`Alt + Space`)**: Raycast-style frosted-glass floating command bar providing instant access across all workspaces, shrinking into an unobtrusive progress pill during execution.
  2. **Live Milestone Checklist**: Real-time progress cards breaking multi-step goals into transparent stages with elapsed execution times (`[✓] Scraped specs (1.2s)` $\rightarrow$ `[⟳] Generating Excel...`).
  3. **Ghost Highlights & Click Ripples**: 100ms translucent boundary glow around interactive targets during UIA/SoM interactions, eliminating visual ambiguity for human observers.
  4. **Interactive Action Approval Cards**: Clean inline cards for high-consequence operations (messaging dispatch, bulk file deletion, process termination) with `[Approve]`, `[Edit]`, `[Cancel]`.
  5. **Slide-Out Artifact & Document Canvas**: Dedicated right-side drawer displaying rich Markdown, interactive CSV/Excel tables, and document exports without cluttering chat history.
  6. **One-Click Saga Rollback Banner**: 10-second toast banner allowing immediate single-click reversal of automated file organization or directory restructuring.
- **Proactive Habit Lifecycle**:
  - Formalized the 3-phase habit transition: **Observation** (temporal pattern logging in `USER.md`) $\rightarrow$ **Gentle Suggestion** (context-aware prompt) $\rightarrow$ **Approved Autopilot** (registered Windows startup task for automated morning/session boot workflows).

---

### Entry 16: Native Windows Spotlight HUD & Web Glassmorphism Implementation (2026-10-01)
- **Context & Design Philosophy**:
  - User requested creating an overlay window taking inspiration from modern browsing / AI desktops (Spotlight, Raycast, Astra) and Makima v1's obsidian-violet palette, adhering to the zero-copy-paste rule.
  - Makima v1 suffered from separate Rust/Slint build dependencies and was decoupled from v2's Hermes while-loop engine.
- **Architectural Implementation**:
  1. **Native SpotlightHUD (`makima/overlay/hud.py`)**:
     - Pure Python `tkinter` + `win32gui` + `ctypes.windll.dwmapi` with zero heavy UI frameworks.
     - Windows 11 DWM Immersive Dark Mode (`DWMWA_USE_IMMERSIVE_DARK_MODE = 20`) and rounded window corners (`DWMWA_WINDOW_CORNER_PREFERENCE = 33` $\rightarrow$ `DWMWCP_ROUND`).
     - Borderless, top-most (`-topmost 1`) floating card centered at 14% of display height with draggable header.
     - Dynamic geometry: compact search bar (68px) expands dynamically to 460px upon submitting queries.
     - Live Step DAG Tracker (Pillar 2): dynamically renders execution stages, active tool invocations, and timings.
     - Quick action chips (`📸 Screen Audit`, `🎵 Play Kick Back`, `🖥️ System Telemetry`, `🧹 Clean Temp`).
     - Global Hotkey Toggle: `Ctrl+Space` (via `pynput.keyboard.GlobalHotKeys`) toggles HUD visibility anywhere across Windows; `Esc` dismisses it.
     - Asynchronous agent execution in background daemon thread with thread-safe UI updates via `root.after()`.
  2. **Web Glassmorphism Overlay (`makima/api/static/overlay.html`)**:
     - High-contrast obsidian-violet palette (`#0B0813`, `#141024`, `#1C1633`, `#2C2250`, `#8B5CF6`).
     - 28px backdrop-filter blur with neon violet glow.
     - Real-time WebSocket connection to `/ws` streaming live DAG execution events.
     - Served directly at `GET /overlay`.
  3. **CLI Integration**:
     - Added `makima overlay` subcommand to `makima/cli/main.py`.
- **Verification**:
  - `tests/verify_overlay.py`: All stages passed (geometry, show/hide, expand/collapse, step DAG emission, text output, HTML integrity, and `GET /overlay` response) with Exit Code 0.

### Entry 17: Makima-owned OSWorld / Daytona benchmark boundary (2026-10-04)
- Fact-checked OSWorld's `reset()` / `predict(instruction, observation)` agent shape and Daytona's `sandbox.process.exec(...)` SDK path against official documentation.
- Added `benchmarks/osworld_makima.py` with a Makima-owned adapter, lazy Daytona lifecycle wrapper, and result records that keep `agent_name=Makima` separate from `reasoning_backend`.
- Added a deterministic contract test proving that tool execution goes through Makima's `HermesAgentEngine` and `ToolRegistry`, even when the backend model is named like Alibaba/Qwen.
- Expanded the isolated `osworld` cascade to five international DashScope Qwen fallbacks: qwen3.8-max, qwen3.7-max, qwen3.7-plus, qwen3.6-plus, and qwen-plus.
- Added a Daytona safety gate: a reachable sandbox alone is insufficient; the runner now requires the official OSWorld runtime before it can emit a Daytona benchmark result, preventing local Makima tool-loop output from being mislabeled as OSWorld.

### Entry 18: Bounded hard Windows OSWorld-inspired task pack (2026-10-04)
- Replaced the shallow note-only Windows smoke task with two deterministic hard
  cases: release-readiness reconciliation and inbox action-queue triage.
- Added official-loop-shaped lifecycle: harness reset, allowlisted observation
  and write tools, max-15-turn default, trajectory events, and exact executable
  post-task evaluation with unexpected-file detection.
- Kept the Windows safety boundary strict: all files are under a disposable
  harness-owned temp directory; writes target only expected outputs; no shell,
  delete, browser, registry, settings, messaging, or arbitrary process tool is
  registered. The result explicitly cannot be reported as an official OSWorld score.
- Live verification: DashScope probe returned `3/8` responding models; the
  three Qwen-VL models responded while five legacy/max fallbacks returned 403
  free-quota exhaustion. Using `qwen3-vl-plus-2025-12-19`, both hard tasks
  passed through Makima: release reconciliation in 10 turns/16 tool calls and
  inbox triage in 7 turns/10 tool calls. The evaluator confirmed no unexpected
  files, then the harness cleaned its temp workspace.
- Hardened the release evaluator after the first live run exposed a Windows
  text-format brittleness: report semantics and manifest binding are checked
  independently, while platform newline and ASCII/Unicode dash differences do
  not turn a correct task into a false negative.

### Entry 19: Makima v2 browser command deck and artifact pipeline (2026-10-04)
- Added `apps/chat_ui`, a Vite/React/TypeScript command deck using the obsidian/violet HUD palette, restrained transitions, responsive layout, and reduced-motion support.
- Implemented functional Models, General, Connectors, Voice, Developer, and Tools settings tabs. Settings are synced through `/api/settings`, `/api/connectors`, and `/api/tools/{name}/enabled`; provider credentials never enter browser state.
- Added provider availability, quota/circuit state, persisted active backend selection, local session persistence, telemetry/debug export, browser speech fallback, and safe tool-risk badges.
- Extended `/ws` with correlated `task_id` events, non-blocking agent tasks, `cancel_task`, `task_cancelled`, selected backend forwarding, and artifact event compatibility.
- Added typed artifact normalization and render cards for code, JSON/log/diff, tables/CSV, charts, Mermaid diagrams, HTML sandbox previews, and image/video/audio media.
- Verification: 20 targeted Python tests pass; frontend `npm test` (2), `npm run lint`, and production `npm run build` pass. Full repository collection remains broader because vendored OSWorld dependencies are not installed.

### Entry 20: Gemini 3.8 Live browser voice bridge and Makima wake word (2026-10-04)
- Switched the v2 native voice default from the legacy `gemini-2.0-flash-exp` identifier to `gemini-3.8-live`.
- Added `/ws/voice`: browser raw PCM microphone frames go to the server-side `GeminiLiveSession`, while native 24kHz response PCM and tool/transcript events return to the browser. API keys never enter the browser.
- Replaced the old browser-only speech input button with a Voice control that supports `Makima` wake-word detection, native Live audio playback, microphone permission fallback, and stop/error states.
- Voice settings now include wake-word enablement and Gemini voice selection. Existing Makima tools such as `launch_application` and `play_song` remain available to the Live tool registry.
- Verification: voice/API contract tests `8 passed`; existing Gemini Live verification passed; frontend TypeScript lint and production build passed.
