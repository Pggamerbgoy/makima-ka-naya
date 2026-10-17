# 📜 Makima v2 — Mandatory Engineering & Swarm Rules
> **Enforcement Level**: STRICT — Zero Exceptions.  
> **Applies To**: All agents, subagents, and developers working on `makima_v2`.

---

## 1. 🐝 Mandatory Ruflo Swarm Execution Protocol

Har implementation aur code modification Ruflo Swarm ke 4-stage autonomous loop ke through execute hoga:
1. **The 4-Stage Autonomous Chain (Zero-Key Mandate)**:
   - **`Stage 1: [ROLE: Coder]`**: Code likhta hai ya files modify karta hai (`write_to_file`, `replace_file_content`).
   - **`Stage 2: [ROLE: Auto-Tester]`**: Code likhte hi *turant* automated test/verification script execute karta hai (`python tests/verify_<module>.py`). Agar test fail ho, toh wapas Coder role me jakar self-heal karta hai.
   - **`Stage 3: [ROLE: Auto-Auditor]`**: Test pass hone par Ruflo static analysis, AST complexity (<15), PII/security scan, aur caller/callee cross-inspection karta hai via `.agents/ruflo_swarm/swarm_pipeline.py`.
   - **`Stage 4: [ROLE: Lead / Consensus]`**: Raft consensus receipt `.swarm/pipeline_ledger.jsonl` me persist karke final completion report deta hai.
2. **Never Stop After Writing Code**:
   - Agent code likhne ke baad kabhi rukega nahi aur user se permission nahi mangega. Pura 4-stage loop usi response turn me autonomously run hoga.
3. **Cognitive Swarm Workers**:
   - IDE ka native Gemini model hi swarm worker node hai, aur Ruflo local CLI/MCP hooks ke sath synchronously integrate hota hai.

---

## 2. 📋 The 3-Step Pre-Implementation Gate (Har Module Banane Se Pehle)

Kisi bhi module, class, tool, ya feature ka code likhne se pehle ye 3 steps execute karna **mandatory** hai:

### Step 1: Explicit TODO Checklist
Har task shuru karne se pehle ek structured TODO list banayi jayegi:
- [ ] Sub-task 1: Exact capability and file to create/edit
- [ ] Sub-task 2: Unit interface and contract definitions
- [ ] Sub-task 3: Callers integration and wiring
- [ ] Sub-task 4: Live verification script execution

### Step 2: Data Flow & Call-Graph Mapping (Kaha Call Ho Raha Hai?)
Module ka code likhne se pehle uska **Data Flow diagram aur Caller-Callee mapping** document karna hoga:
- **Caller Modules**: Kaun-kaun se files/classes is module ko call karenge?
- **Callee Modules**: Ye module kin external libraries/tools ko call karega?
- **Input Parameters & Types**: Exact arguments, types, aur default values.
- **Output Return Format**: Return type (`dict`, `str`, `Pydantic model`) aur error structure.
- **Silent Regression Guard**: Kya signature change se kisi existing caller me silent `TypeError` ya `KeyError` create ho sakta hai?

### Step 3: Verification & Live Test Gate (Kaam Kar Raha Hai Ya Nahi?)
- Code likhne ke baad sirf "code looks clean" bol kar aage badhna **strictly banned** hai.
- Har module ke sath ek standalone runnable verification script (`tests/verify_<module>.py`) ya live execution command chalakar proof verify karna hoga:
  - Kya module actual runtime par execute ho raha hai?
  - Kya return values expected schema se match kar rahi hain?
  - Kya error handling aur fallbacks sahi kaam kar rahe hain?

---

## 3. 🔍 Callee + All Callers Mandate

- Jab bhi kisi function, tool, ya class ko banaya ya modify kiya jaye, **sirf uss file ko dekh kar rukna STRICTLY BANNED hai**.
- Codebase me jaha-jaha us module ko call kiya jata hai (har ek caller file aur block of code), unhe line-by-line open karke parameters aur return types cross-verify karna mandatory hai.

---

## 4. ⚡ Zero-Hardcoding & 100% Dynamic Mandate

- **Dynamic Tool Discovery**: Tools `@tool` decorator se auto-scan honge (`tools/**/`).
- **Dynamic Model Probing**: Models env vars aur Ollama `/api/tags` se runtime detect honge.
- **Dynamic Skills Engine**: `~/.makima/skills/*.md` se live Markdown load hoga.
- **Dynamic Paths**: `pathlib.Path.home()` aur `platform.system()` se OS paths resolve honge.
- **Dynamic Context**: Active model ki true context window (1M vs 128k vs 8k) dynamically calculate hogi.

---

## 5. 💰 Free-Tier & Zero-Cost First Guarantee

- **Primary Engine**: Google GenAI SDK (Gemini 2.5 Flash free tier, Gemini 3.8 Live audio).
- **OpenAI & Anthropic**: Sirf free tiers / free endpoints (OpenRouter Free `openrouter/free`, Groq Free, Cerebras Free, local Ollama).
- **Zero Paid Keys**: Kisi bhi paid credit ya mandatory credit card API subscription ki zaroorat nahi hogi.

---

## 6. 🚫 Strict Ban on Blind Copy-Pasting & Ruthless Bloat Omission

- **Zero Blind Copy-Paste**: Old Makima (`apps/brain/`, `v1`) se code blindly copy-paste karna **STRICTLY BANNED** hai.
- **Architectural Divergence**: Makima v2 ek fresh, modern, clean architecture hai jo Nous Research Hermes Agent pattern par based hai. Bahut si cheezein v1 se radically different hongi.
- **Ruthless Pruning (Unneeded/Low-Value Omission)**:
  - Agar purani Makima ka koi tool, feature, abstraction, helper function, ya parameter v2 ke clean design ke liye unnecessary ya over-engineered lagta hai, **usko bilkul implement mat karo**.
  - **No Legacy Baggage**: v1 ke 4,300-line monolithic god-modules (`system_tools.py`), 2,900-line SDK bridge bloat, aur fragile Win32 workarounds ko v2 me entry nahi milegi.
  - Sirf wahi implement karo jo modular, clean, lightweight, strictly verified, aur Hermes architecture ke standard ko meet kare.

---

## 7. 📚 Mandatory Library-First & Zero-Reinvention Protocol

- **Never Reinvent the Wheel**: Jo capability existing libraries, SDKs, built-ins, ya official packages se provide hoti hai, uska custom logic hand-roll karna **STRICTLY BANNED** hai.
- **The 3-Question Verification Gate (Before Writing ANY Code)**:
  1. **Python Stdlib?** (`pathlib`, `shutil`, `json`, `difflib`, `tempfile`, `hashlib`, `asyncio`, `re`) -> Stdlib directly use karo.
  2. **Installed Package?** Check `pyproject.toml` (`pydantic`, `httpx`, `psutil`, `pywin32`, `pywinpty`, `playwright`, `openpyxl`, `docx`, `pptx`, `fastembed`, `aiosqlite`) -> Package APIs directly use karo.
  3. **Existing Makima Subsystem?** (`get_settings()`, `@tool` in `ToolRegistry`, `ParetoRouter`, `StateMemory`, `EpisodicMemory`) -> Subsystem reuse karo.
- **Strictly Banned Anti-Patterns**:
  - ❌ Hand-rolling file copy/tree operations (use `shutil`).
  - ❌ Hand-rolling process monitoring or killing (use `psutil`).
  - ❌ Hand-rolling Win32 window management with ctypes (use `pywin32` / `win32gui`).
  - ❌ Hand-rolling terminal emulation (use `pywinpty`).
  - ❌ Hand-rolling document creation (use `openpyxl`, `python-docx`, `python-pptx`).


