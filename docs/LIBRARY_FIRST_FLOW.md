# 🧠 Makima v2 — The Library-First & Resource-Reuse Engineering Flow
> **Core Mandate for Incoming AI**: "DO NOT CODE WHAT ALREADY EXISTS."  
> Pehle verify karo ki kya koi official SDK, battle-tested library, pre-trained model, ya public API already ye kaam karti hai. Agar karti hai, toh directly use karo — hand-rolled custom code likhna strictly banned hai.

---

## 1. 🔍 The 4-Gate Discovery Flow (Humne Resources Kaise Dhunde)

Jab bhi Makima v2 ke kisi subsystem ka plan bana, humne is 4-Gate protocol se filter kiya:

```
[Problem / Feature Required]
          ↓
  Gate 1: Python Stdlib?
  (pathlib, asyncio, inspect, json, subprocess)
          ↓ (Agar nahi)
  Gate 2: Industry-Standard PyPI Package?
  (pydantic, httpx, psutil, openpyxl, sounddevice)
          ↓ (Agar nahi)
  Gate 3: Official Model SDK / Protocol?
  (google-genai, openai, anthropic, mcp)
          ↓ (Agar nahi)
  Gate 4: Pre-Trained Open Model or Free Public API?
  (fastembed ONNX, Jina Reader, Open-Meteo)
          ↓
[Custom Code ONLY for Business Logic / While-Loop Orchestration]
```

---

## 2. 📊 Subsystem-by-Subsystem: "What We Code vs What We Reuse"

| Subsystem | What Developers Usually Waste Time Hand-Rolling (❌ BANNED) | Pre-Existing Battle-Tested Resource We Reused (✅ ADOPTED) | Why It's 10x Better |
|---|---|---|---|
| **JSON Schemas from Python Functions** | Writing manual JSON schemas or custom regex parsers. | **`pydantic.TypeAdapter` / `inspect.signature`** | Pydantic v2 automatically function signature ko strict OpenAI-compatible JSON schema me convert kar deta hai. |
| **Real-Time Voice Speech-to-Speech** | Custom WebRTC servers, manual audio buffering, custom voice pipelines. | **`google-genai` (Gemini 3.8 Live WebSocket)** | Single WebSocket connection me 16kHz PCM in aur 24kHz PCM out with native barge-in (interruption). |
| **Multimodal Real-Time Voice (Zero TTS)** | Conventional standalone TTS engines (Kokoro, Edge-TTS) needing clumsy STT + LLM + TTS chaining. | **`google-genai` (Gemini 3.8 Live Native Audio)** | Zero TTS chaining latency: direct bidirectional audio generation in single WebSocket with natural tone & barge-in. |
| **Speech-to-Text (STT) & Silence Detection** | Manual energy-threshold VAD algorithms, vanilla OpenAI Whisper. | **`faster-whisper` + Silero VAD** | CTranslate2 engine Whisper se 4x fast hai aur Silero VAD silence/music ko automatically filter karta hai. |
| **Browser Anti-Detect & Stealth** | Custom Puppeteer scripts, writing manual stealth evasions, CDP patches. | **`patchright`** | Playwright ka drop-in replacement jo Chrome DevTools protocol leaks aur `navigator.webdriver` ko internally strip karta hai. |
| **Webpage to LLM Markdown Conversion** | Writing custom HTML parsers, boilerpipe, readability regex. | **Jina Reader API (`https://r.jina.ai/<url>`)** | Kisi bhi URL ke aage `https://r.jina.ai/` lagane se Jina uska pura layout, ads, aur JS hata kar clean Markdown return karta hai. |
| **Windows Interactive Terminal** | Writing custom Windows console hooks, raw subprocess pipes (which freeze). | **`pywinpty` (Windows ConPTY)** | Windows Pseudoconsole API ko wrap karta hai; interactive prompts (`[y/N]`, `git`) freeze nahi hote. |
| **Audio Microphone & Speaker I/O** | `pyaudio` (fails on Windows without MSVC C++ compiler). | **`sounddevice`** | Pre-bundled PortAudio DLLs in wheels, zero compilation required, native NumPy array stream. |
| **Vector Similarity Search** | Heavy vector databases (Pinecone, ChromaDB, Milvus, Qdrant). | **`sqlite-vec` + `fastembed`** | In-process SQLite extension + ONNX Runtime BGE embeddings. Zero Docker containers, zero cloud fees. |
| **Excel & Document Generation** | Writing raw XML, manual CSV formatters, HTML-to-PDF via WeasyPrint (GTK crash). | **`openpyxl` + `python-docx` + Playwright `page.pdf()`** | Pure Python document engines + Chromium's built-in PDF printer (100% reliable on Windows). |
| **Tool Calling Extensibility** | Custom tool invocation protocols. | **Anthropic's Model Context Protocol (`mcp[cli]`)** | 2026 ka industry standard. Makima external community MCP servers (GitHub, Filesystem, Postgres) bina code likhe use kar sakti hai. |
| **Multi-Platform Chat Daemon** | Building custom WebSocket clients for Telegram/Discord/Slack. | **`python-telegram-bot` + `discord.py` + `slack-bolt`** | Official async SDKs jo webhooks, long polling, slash commands, aur media attachments natively handle karte hain. |

---

## 3. 🎯 Rule for the Incoming AI (Naye AI ke Liye Clear Directive)

Jab naya AI session me aaye, use yeh golden rule yaad rakhna hoga:

> **"Your job is NOT to write complex utility libraries from scratch. Your job is to glue and orchestrate these verified resources using clean, modular Python architecture."**

1. **HTTP calls karni hain?** -> `httpx[http2]` connection pool use karo. Naya HTTP client mat banao.
2. **Settings load karni hain?** -> `pydantic-settings` use karo. Manual file reading mat karo.
3. **Process monitor karna hai?** -> `psutil` use karo. Windows tasklist parsing mat karo.
4. **Tool schemas generate karni hain?** -> Pydantic TypeAdapter use karo. Hand-crafted schemas mat likho.
5. **Code run karna hai?** -> Local subprocess with `pywinpty` / Docker SDK use karo. Raw pipes mat kholo.
