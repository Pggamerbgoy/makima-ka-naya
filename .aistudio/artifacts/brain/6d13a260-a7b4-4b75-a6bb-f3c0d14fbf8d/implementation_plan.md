# Makima v2 — Minimalist Linear / Raycast UI Redesign

Redesign the entire Makima v2 workspace from a neon-purple, badge-heavy "vibe-coded" layout into a precision-engineered **Linear / Raycast monochrome slate & zinc** command environment. The new design pairs strict structural minimalism and crisp hairline geometry with curated, high-craft fun elements, backed by a clean reactive state layer and mutually exclusive tab routing.

## User Review & Critical Decisions

> [!IMPORTANT]
> This revised plan incorporates your architectural feedback alongside your aesthetic preferences:

- **Confirmed Layout Architecture (Tabs, Not Simultaneous Panes)**: `Chat Stage`, `Artifacts Library`, and `Telemetry Workspace` are **mutually exclusive tabs** controlled by the Header View Switcher (`activeView: 'chat' | 'artifacts' | 'telemetry'`). Only one primary view renders in the main viewport at a time; `Canvas Studio` slides over as a secondary drawer when editing an artifact.
- **Confirmed Header Zone Separation & Persistent Daemon Status**:
  - **Daemon Status Moved to Header Chrome**: Removed from the collapsible sidebar so system health (`Local Live` / `Reconnecting` / `Offline`) is always visible at a glance even when the sidebar is collapsed.
  - **Decoupled `ModelPicker` & `System Actions`**: Separated into distinct header zones so model selection never crowds system utilities (`Daemon Status`, `Plugins`, `Settings`, `Theme`).
- **Confirmed State & Streaming Data Layer**: Added an explicit **Brain Event & State Store Layer** (`useMakimaSocket` + RAF-batched chunk/step reducer + `api` sync) between the Python backend and the React view tree to handle in-flight agent steps, streaming token deltas, security approval gates, and error recovery deterministically.
- **Confirmed Aesthetic & "Engineered Fun"**: **Linear / Raycast Monochrome Slate & Zinc** (`#09090B` / `#121215` dark; `#FAFAFA` / `#FFFFFF` light) with 1px hairline borders, `Outfit` + `Plus Jakarta Sans` + `JetBrains Mono` (`tabular-nums`), and tactile micro-delights (Raycast-style HUD quip popover on the brand mark, tactile prompt shuffler, subtle Web Audio synthesis, and hover-revealed reactions).
- **Confirmed Default Zero-State (`ZeroHero`)**: Clean blank session stage with a centered composer, 4 minimal text prompts, and a 1-click showcase loader.

---

## 1. Overview & Core Concept

- **What It Does**: Makima v2 is an autonomous desktop orchestration and multi-agent workspace supporting real-time streaming chat, multi-step tool execution inspection, a slide-over Canvas code/diagram studio, an Artifact library, live system telemetry, and MCP/OpenAPI plugin management.
- **Target Audience / Persona**: Software engineers, systems architects, and power users who expect native desktop-grade speed, keyboard-first ergonomics (`⌘K` session palette, `⌘S` canvas save, `Esc` interrupt), and zero visual clutter.
- **Key Value**: Eliminates every trace of "AI template slop" (purple gradients, glowing orbs, redundant pill badges, and cramped toolbars) while grounding the view hierarchy in a predictable state/event architecture.

### Core Component Glossary
- **`ZeroHero` (Empty-State Command Stage)**: The centered initial view rendered inside `Chat Stage` when the active session has zero messages; houses the status kicker, headline, prompt shuffler, 4 starter capability prompts, and an on-demand sample report loader.
- **`Stepper` (Multi-Step Agent Execution Trace)**: The collapsible inline timeline rendered at the top of an assistant message (`ExecutionStepsAccordion`) that displays live in-flight reasoning stages, tool calls with parameter/output inspection, blocking security permission prompts (`Allow Once` / `Deny`), and tabular execution durations (`142ms`).

---

## 2. User Experience & Visual Design

### Key User Flows
1. **Focused Zero-State Launch (`ZeroHero`)**: Opening the app presents a calm, centered command stage. Users can click any of the 4 minimal capability prompts to populate the composer, click *Shuffle prompt* to cycle ideas, or click *Load sample research report* to immediately inspect multi-modal artifacts (tables, SVG charts, Mermaid diagrams, and code).
2. **Streamlined Conversation & In-Flight `Stepper`**: Messages render in a clean editorial column (`max-w-3xl`). While the Python brain executes tools, `Stepper` streams live tool status and collapses into a single-line monospace summary (`Executed 3 steps · 142ms`) once complete. Message footers show quiet unboxed timestamps and primary actions (`Copy`, `Raw`, `Listen`, `Export`, `Retry`) with hover-revealed reactions.
3. **Mutually Exclusive Tab Switching**: Clicking `Chat`, `Artifacts`, or `Telemetry` in the center header tab bar swaps the main viewport cleanly without multi-pane crowding.
4. **Slide-Over Canvas Studio**: Clicking *Open in Canvas* on any artifact in `Chat` or `Artifacts` slides open the right-hand `Canvas Studio` drawer with monospace line gutters, instant segmented mode switching (`Edit` / `Preview` / `Split`), and a clean inline AI instruction bar.

### Visual Identity & Theme
- **Aesthetic Direction**: **Linear / Raycast Utilitarian Minimalism** — High-density scannability, flat single-elevation surfaces, and crisp `1px` hairline geometry.
- **Color Palette & Mood (60-30-10 Discipline)**:
  - *Dark Posture (Default)*:
    - **60% Dominant Canvas (`--bg`)**: Deep Carbon Zinc `#09090B`
    - **30% Structural Surfaces (`--sidebar`, `--panel`, `--panel-2`, `--border`)**: Elevated Zinc `#111114`, Surface `#18181C`, Subtle Hairline `rgba(255, 255, 255, 0.07)`, Muted Text `#8E8E98`
    - **10% Accent Budget (`--accent`, Semantic Status)**: Crisp Zinc-White primary CTAs (`#F4F4F5` surface with `#09090B` text) paired with a restrained indigo focus ring (`#6366F1`); semantic emerald (`#10B981`), amber (`#F59E0B`), and rose (`#F43F5E`) always paired with explicit text labels.
  - *Light Posture*:
    - **60% Dominant Canvas (`--bg`)**: Crisp Alabaster `#FAFAFA`
    - **30% Structural Surfaces (`--sidebar`, `--panel`, `--border`)**: Cool Stone `#F4F4F5`, Pure White `#FFFFFF` panels, Hairline `rgba(0, 0, 0, 0.08)`, Muted Text `#646470`
    - **10% Accent Budget**: Carbon `#18181B` primary buttons and `#4F46E5` focus state.
- **Typography & Hierarchy (The 2+1 Font Rule)**:
  - *Display & Navigation*: `Outfit` (600 SemiBold, tight `-0.02em` tracking) for workspace headers and brand lockup.
  - *UI & Body Prose*: `Plus Jakarta Sans` (400 Regular / 500 Medium, `14px` UI baseline, `15px` prose with `1.65` line-height).
  - *Data, Telemetry & Code*: `JetBrains Mono` with strict `font-variant-numeric: tabular-nums` on all latency figures, percentages, counts, and timestamps.

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1: Mutually Exclusive Tabs vs. Simultaneous Multi-Pane Layout**
  - *Chosen Approach*: Single active viewport driven by the Header View Switcher (`Chat` | `Artifacts` | `Telemetry`), with `Canvas Studio` as an on-demand slide-over drawer.
  - *Why*: Simultaneous 3-pane layouts crush horizontal reading measure on standard 1280px–1440px laptops. Exclusive tabs give 100% viewport breathing room to whichever task the user is performing.
- **Decision 2: Moving Daemon Status to Header Chrome & Decoupling `ModelPicker`**
  - *Chosen Approach*: Promote `DaemonStatus` out of the collapsible sidebar into the right header zone, and move `ModelPicker` into the left context zone next to the session title.
  - *Why*: Users collapse the sidebar during deep work but still need continuous visibility into backend connection health (`Local Live` vs `Offline`). Separating `ModelPicker` to the left prevents right-hand header crowding.
- **Decision 3: Explicit Reactive State & Event Buffer Layer**
  - *Chosen Approach*: Centralize WebSocket event ingestion (`chunk`, `tool_call`, `tool_result`, `thought`, `permission_request`, `artifact_ready`, `error`) and REST polling into a structured state layer with `requestAnimationFrame` chunk batching and deterministic local fallback.
  - *Why*: Prevents UI jitter during high-frequency token streaming and ensures every view component receives normalized loading, in-flight step, and error states.

---

## 4. Technical Architecture & Data Strategy

### Architecture, State Layer & View Hierarchy Diagram

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       PYTHON BRAIN / LOCAL DAEMON BACKEND                       │
│         WebSocket (/ws, /ws/voice)  ·  REST (/api/status, /sessions, /mcp)      │
└───────────────────┬─────────────────────────────────────────┬───────────────────┘
                    │ StreamEvents (chunk, tool_call, error)  │ JSON Payloads
                    ▼                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    MAKIMA REACTIVE STATE & EVENT STORE LAYER                    │
│  · Socket & Fallback Controller (connectionState, activeTaskId, reconnect)      │
│  · RAF Stream Reducer (60fps chunk batching, in-flight Stepper state machine)   │
│  · Session & Settings Store (localStorage sync, optimistic rollback, artifacts) │
└───────────────────┬─────────────────────────────────────────┬───────────────────┘
                    │                                         │
                    ▼                                         ▼
┌───────────────────────────────────────┐ ┌───────────────────────────────────────┐
│        COLLAPSIBLE SIDEBAR NAV        │ │         PERSISTENT HEADER BAR         │
│  · Brand Lockup + HUD Quip Popover    │ │  [Zone 1: Context & Model]            │
│  · Primary Action: + New Session      │ │   Sidebar Toggle · Session · ModelPick│
│  · Command Search Trigger (⌘K)        │ │  [Zone 2: Exclusive View Switcher]    │
│  · Recent Sessions List (Pin/Delete)  │ │   (•) Chat  ( ) Artifacts ( ) Telemet.│
│  · Footer: Quiet Settings Shortcut    │ │  [Zone 3: Daemon Status & Actions]    │
└───────────────────────────────────────┘ │   DaemonStatus · Plugins · Set · Theme│
                                          └───────────────────┬───────────────────┘
                                                              │
                                       ┌──────────────────────┴──────────────────┐
                                       │   EXCLUSIVE TAB ROUTER (activeView)     │
                                       └───┬─────────────────┬───────────────┬───┘
                                           │                 │               │
                            (if 'chat')    ▼  (if 'artifacts')▼ (if 'telemetry')▼
                                    ┌──────────────┐  ┌──────────────┐ ┌──────────────┐
                                    │  CHAT STAGE  │  │  ARTIFACTS   │ │  TELEMETRY   │
                                    │  · ZeroHero  │  │  · Search/Flt│ │  · KPI Grid  │
                                    │  · Messages  │  │  · Card Grid │ │  · Cascade   │
                                    │  · Stepper   │  └──────┬───────┘ │  · Event Log │
                                    │  · Composer  │         │         └──────────────┘
                                    └──────┬───────┘         │
                                           │ (onOpenCanvas)  │
                                           └────────►────────┘
                                                    ▼
                                    ┌────────────────────────────────┐
                                    │  SLIDE-OVER CANVAS STUDIO      │
                                    │  · Edit / Preview / Split      │
                                    │  · Line Gutter + AI Refine Bar │
                                    └────────────────────────────────┘
```

### Data Model, State Flow & Error Recovery
- **Streaming & In-Flight Agent State (`messages` + `chunkBufferRef`)**:
  - Incoming `chunk` events accumulate in `chunkBufferRef` and flush at most once per animation frame (`requestAnimationFrame`), preventing React render thrashing during fast token generation.
  - Incoming `tool_call`, `thought`, `permission_request`, and `tool_result` events mutate the target assistant message's `steps: ExecutionStep[]` array in place, driving the `Stepper` component through `running` $\rightarrow$ `awaiting_approval` $\rightarrow$ `completed` / `failed` states with millisecond durations.
  - If the WebSocket disconnects mid-generation or the local daemon is unreachable, the controller transitions cleanly either to an explicit interrupted state with a `Retry` action or to the deterministic local agent simulation (`runSimulatedAgentTurn`) so the UI remains 100% interactive in preview environments.
- **Optimistic Settings & Connector State**:
  - Updating `settings`, `connectors`, or `tools` applies optimistically to the UI state and rolls back automatically with an inline toast if the backend save fails.
