# Makima v2 architecture map

## Runtime boundaries

- `makima/core/engine.py`: Hermes tool-loop engine; provider responses become
  tool calls and final `EngineResult` values.
- `makima/provider/`: provider adapters and `ParetoRouter`; the model selected
  here is a reasoning backend, not the benchmark agent identity.
- `makima/tools/registry.py`: schema synthesis and explicit tool dispatch.
- `benchmarks/osworld_makima.py`: OSWorld-shaped `reset`/`predict` adapter for
  an official VM/runtime; it must not label a local smoke test as OSWorld.
- `benchmarks/windows_safe_osworld.py`: bounded Windows host benchmark. It
  owns a disposable temp tree, exposes an allowlist, and evaluates exact
  task outputs without granting general shell, filesystem, or process control.
- `benchmarks/run_windows_safe_osworld.py`: resets one safe task, runs Makima
  for a bounded number of turns, executes the post-task evaluator, and emits a
  structured result with trajectory events.

## Data flow

```text
SafeTask seed files
  -> harness-owned temp workspace
  -> allowlisted ToolRegistry schemas
  -> HermesAgentEngine / ParetoRouter
  -> bounded file transformations
  -> exact evaluator + trajectory JSON
```

## Safety invariants

- Every task filename must be in the task's seed/output allowlist and resolve
  beneath the harness root.
- Writes are limited to expected output files; no delete tool is registered.
- Notepad is optional and can only open an expected output started by the
  harness. Cleanup never kills by PID.
- The Windows safe suite reports `official_osworld_score: false`; official
  OSWorld scores require the official VM, task assets, and evaluator.

## Verification surface

- `tests/test_windows_safe_osworld.py`: allowlist, path traversal, exact and
  semantic evaluator, manifest, and task-catalog contracts.
- `tests/test_osworld_makima.py`: attribution and engine/registry contracts.

## Browser command deck

`apps/chat_ui` is the browser-facing Makima v2 surface. It talks to the same
FastAPI process as the native clients and does not store provider credentials.

```text
FastAPI REST settings/status/tools/connectors
              +
FastAPI WebSocket task_id event stream
              |
          React command deck
              |
artifact normalizer -> renderer registry -> card / Canvas / download
```

The WebSocket receive loop remains active while Hermes runs execute as asyncio
tasks, which makes stop/cancel work without dropping the connection. Typed
`artifact_ready` events and plain Markdown fences/tables share the frontend
normalization path. HTML previews use a sandboxed iframe; code cards do not
show a run action because no safe sandbox execution endpoint exists today.

For a local release, `makima.api.app:create_app` mounts `apps/chat_ui/dist`
after the API and WebSocket routes. `MAKIMA_UI_DIST_DIR` selects a packaged
build and `MAKIMA_SERVE_UI=false` disables static serving for API-only runs.
Cross-origin access is limited to the local development origins (or the
comma-separated `MAKIMA_UI_ALLOWED_ORIGINS` override); WebSocket origins use
the same allowlist. The UI keeps a versioned, size-bounded session envelope,
does not replay an interrupted foreground task, and validates/sanitizes
untrusted artifact URLs, HTML, and Mermaid SVG before rendering.

## Shared runtime and extensibility

`makima/runtime.py` is the production construction boundary for engines and
registries. It wires episodic, state, vector, preference-learning, and skills
services together and supports bounded session rehydration by session ID.
API, WebSocket, CLI, overlay, and gateway entry points use this boundary.

Gateway adapters share the daemon security manager and engine. Remote gateway
queries receive a capability-filtered registry by default; high-impact desktop,
filesystem, terminal, deletion, and execution tools are not exposed to the
default `chat` profile.

`makima/plugins.py` loads only enabled, explicitly trusted local manifests and
optionally connects trusted MCP stdio servers when the `mcp` extra is installed.
MCP tools are normalized into the existing registry and inherit the same engine
guardrails and capability filtering.
