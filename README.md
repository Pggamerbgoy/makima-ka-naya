# 👑 Makima v2 — Autonomous Multi-Platform Desktop AI Assistant

> **Architecture**: Inspired by **Nous Research Hermes Agent** (`nousresearch/hermes-agent`) pattern.  
> **Routing**: Dynamic Zero-Cost Pareto Frontier Router.  
> **Automation**: Native Microsoft UI Automation (UIA) & Set-of-Marks (SoM) visual grounding without vision.  
> **Voice**: Native Gemini 3.8 Live Bidirectional Audio with hardware barge-in (Zero TTS).  
> **Test Status**: **21/21 Test Suites + 10s Continuous Desktop Benchmark Passed (100% Exit Code 0)**.

---

## ⚡ Key Highlights

1. **Autonomous While-Loop Engine & Fake Tool Defense (`makima/core/engine.py`)**:
   - Transparent, modular Hermes-style while-loop.
   - Dynamic middle-turn context compression protecting goal context (Head) and recent conversation (Tail).
   - 4-layer defense against hallucinated tool calls (fuzzy `difflib` suggestion, Pydantic v2 argument bounds, JSON repair, repetition breaker).
   - Dual-layer guardrails intercepting destructive OS commands and redacting credentials using Shannon entropy ($H > 4.3$).

2. **Zero-Vision Desktop UI Automation & Visual Grounding (`makima/tools/desktop/uia.py`)**:
   - Operates Windows applications via native Microsoft UI Automation (UIA) and Win32 IPC in sub-second time (<500 tokens).
   - Optional Set-of-Marks (SoM) bounding box annotations (`annotate_window_som`) and Astra-grade unified facade (`computer_use`).
   - Native Windows Notification Center toast alerts (`show_desktop_notification`).
   - Dedicated thread pool attaching to the interactive desktop station (`win32service.OpenDesktop`) with COM STA isolation.
   - Battle-tested 6-stage continuous physical desktop benchmark in **10.04 seconds**.

3. **Gemini 3.8 Live Native Voice (`makima/voice/`)**:
   - Full-duplex WebSocket stream powered by `google-genai` SDK.
   - Direct 24kHz PCM audio generation; **Zero standalone TTS**.
   - Real-time microphone RMS volume monitoring for instant hardware barge-in.
   - Live in-stream tool execution during voice conversation.

4. **Dynamic Zero-Cost ParetoRouter (`makima/provider/router.py`)**:
   - Dynamically probes active credentials and local Ollama daemon (`GET http://localhost:11434/api/tags`).
   - Task cascades prioritize free quotas (Groq, Gemini, OpenRouter Free) and 100% offline local models (`qwen2.5-coder:7b`).
   - Jittered 3-state circuit breakers with EWMA latency scoring.

5. **Self-Improving Skills & Dual-Tier Memory (`makima/memory/` & `makima/skills/`)**:
   - **Tier 1**: Human-inspectable `MEMORY.md` and `USER.md` prompt injection.
   - **Tier 2**: Async SQLite WAL database via `aiosqlite` with FTS5 full-text keyword retrieval.
   - **Skills Engine**: Dynamic scanner of `~/.makima/skills/**/*.md` with `@tool save_learned_skill` enabling autonomous skill authoring.

6. **Multi-Platform Messaging Gateway Daemon (`makima/gateway/`)**:
   - Single supervisor daemon (`makima gateway run`) supporting Telegram, Discord, WhatsApp, and Email.
   - Ephemeral 6-character pairing codes (`MK-XXXX`, 15m TTL) with persistent allowlist authorization.
   - Integrated `APScheduler` for one-shot reminders and recurring cron routines.

7. **Rich Terminal CLI & FastAPI WebSockets (`makima/cli/` & `makima/api/`)**:
   - Interactive terminal REPL (`makima chat`) and system diagnostics (`makima status`).
   - FastAPI server with REST `/api/chat` and real-time streaming WebSocket `/ws` emitting intermediate planning, tool calls, and results.

---

## 📁 Repository Map

```text
makima_v2/
├── configs/
│   └── settings.yaml             # Master system configuration
├── docs/
│   ├── SYSTEM_GUIDE.md           # Comprehensive technical architecture & guide
│   └── DEVLOG.md                 # Engineering decision & tradeoff log
├── makima/
│   ├── api/                      # FastAPI server & real-time WebSocket bridge
│   │   ├── app.py                # REST endpoints (/health, /api/status, /api/tools, /api/chat)
│   │   └── ws.py                 # Streaming WebSocket route (/ws)
│   ├── cli/                      # Rich Terminal CLI
│   │   └── main.py               # Commands: chat, tools, gateway, status
│   ├── config.py                 # Pydantic-settings dynamic configuration engine
│   ├── core/                     # Hermes autonomous agent core
│   │   ├── context.py            # Head/Tail context compressor
│   │   ├── engine.py             # HermesAgentEngine while-loop
│   │   └── guardrails.py         # Dangerous command block & secret redactor
│   ├── gateway/                  # Multi-platform messaging gateway daemon
│   │   ├── daemon.py             # Master supervisor loop
│   │   ├── scheduler.py          # APScheduler cron & reminder manager
│   │   ├── security.py           # Allowlist & pairing code authorizer
│   │   └── adapters/             # Platform adapters (Telegram, Discord, WhatsApp, Email)
│   ├── memory/                   # Dual-tier memory subsystem
│   │   ├── state.py              # Tier 1: MEMORY.md & USER.md prompt injector
│   │   └── episodic.py           # Tier 2: Async SQLite WAL with FTS5 search
│   ├── provider/                 # Zero-cost Pareto model router
│   │   ├── circuit_breaker.py    # 3-state jittered circuit breaker
│   │   ├── router.py             # Dynamic candidate ranking & task cascades
│   │   └── adapters/             # Provider implementations (Gemini, OpenAI-compatible, Ollama)
│   ├── skills/                   # Self-improving skills engine
│   │   ├── loader.py             # Dynamic YAML frontmatter markdown loader
│   │   └── synthesizer.py        # Autonomous skill writer tool
│   ├── tools/                    # Modular toolsets with @tool auto-discovery
│   │   ├── browser/              # HTTP web search & Playwright automation
│   │   ├── desktop/              # Zero-Vision Microsoft UI Automation (UIA) tools
│   │   ├── documents/            # Excel (.xlsx), Word (.docx), PowerPoint (.pptx)
│   │   ├── filesystem/           # Safe I/O & SAGA pre-state snapshot rollback
│   │   ├── media/                # Native Windows media control & master volume
│   │   ├── os/                   # Processes, windows, apps, and hardware telemetry
│   │   ├── terminal/             # Sandboxed subprocess runner & ConPTY terminal
│   │   └── registry.py           # @tool decorator & Pydantic JSON schema synthesizer
│   └── voice/                    # Multimodal voice subsystem
│       ├── audio_io.py           # Low-latency SoundDevice PCM streaming & playback
│       ├── controller.py         # LiveVoiceController with instant barge-in
│       └── gemini_live.py        # Gemini 3.8 Live bidirectional audio WebSocket stream
├── tests/                        # 21 Standalone verification test suites
└── TODO.md                       # Master implementation checklist
```

---

## 🚀 Quickstart

### 1. Interactive Terminal Chat
```powershell
python -m makima.cli.main chat
```

### 2. Single-Turn Query
```powershell
python -m makima.cli.main chat -p "List all open windows on my desktop and check system memory"
```

### 3. Inspect Discovered Tools
```powershell
python -m makima.cli.main tools list
```

### 4. System Diagnostics Dashboard
```powershell
python -m makima.cli.main status
```

### 5. Start Multi-Platform Gateway Daemon
```powershell
python -m makima.cli.main gateway run --host 127.0.0.1 --port 8080
```

### 6. Start FastAPI & WebSocket Server
```powershell
python -m uvicorn makima.api:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

For a local release build, compile the UI first; FastAPI then serves
`apps/chat_ui/dist` and the API from the same origin:

```powershell
cd apps/chat_ui
npm install
npm run build
cd ../..
python -m uvicorn makima.api:create_app --factory --host 127.0.0.1 --port 8000
```

Use `MAKIMA_UI_DIST_DIR` for a packaged UI directory or
`MAKIMA_SERVE_UI=false` for an API-only process.

### 7. Launch Windows Native Spotlight HUD Desktop Overlay
```powershell
# Pure Windows Native GUI with Acrylic Blur & DWM Dark Mode
# Toggle anywhere on Windows with [Ctrl + Space], dismiss with [Esc]
python -m makima.cli.main overlay
```

---

## 🧪 Verification & Regression Testing

### 1. Run Complete Automated Smoke Suite
```powershell
python -m pytest tests/test_smoke.py
```

### 2. Run All 21 Standalone Subsystem Verification Suites
```powershell
python -c "import subprocess, sys, pathlib; sys.exit(0 if all(subprocess.run([sys.executable, str(f)]).returncode == 0 for f in sorted(pathlib.Path('tests').glob('verify_*.py'))) else 1)"
```

### 3. Run Continuous 10-Second Physical Desktop Benchmark
```powershell
python tests/test_scenario_benchmark.py
```

### 4. Run Live User Capability Verification Suite
```powershell
python tests/test_capabilities_live.py
```

For in-depth architectural details, call-graphs, and data flows, refer to [`docs/SYSTEM_GUIDE.md`](docs/SYSTEM_GUIDE.md), [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md), [`docs/WORKFLOW.md`](docs/WORKFLOW.md), and [`docs/DEVLOG.md`](docs/DEVLOG.md).
