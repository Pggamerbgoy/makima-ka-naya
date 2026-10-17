# Makima OSWorld / Daytona benchmark

The benchmark identity is **Makima**. Alibaba/Qwen/Gemini/etc. is an internal
reasoning backend selected by Makima's provider router; it is not the agent
being evaluated.

## Runtime boundary

```text
OSWorld task + observation
        -> MakimaOSWorldAgent
        -> HermesAgentEngine
        -> provider router (reasoning_backend)
        -> Makima ToolRegistry
        -> Daytona/VM-facing tools
```

The adapter is in `benchmarks/osworld_makima.py`. It supplies the standard
`reset()` / `predict(instruction, observation)` shape and a richer async
`run_task()` path. Every result contains both `agent_name: Makima` and the
actual `reasoning_backend`, so reports cannot silently rename the run after the
backend model.

## Local contract test

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m pytest tests\test_osworld_makima.py -q -p no:cacheprovider
```

The test uses a deterministic backend and a real `HermesAgentEngine` plus
`ToolRegistry`; it verifies that a tool call executes through Makima and that
the result keeps Makima and the backend identities separate.

The Daytona command now performs a hard preflight: it requires both a reachable
Daytona process bridge and the official OSWorld runtime (`desktop_env/` plus
`lib_run_single.py`, discoverable through `OSWORLD_ROOT`, the bundled
`third_party/OSWorld` checkout, or Python imports).
Until that runtime is present, it refuses to run the local Makima tool loop so a
host smoke test cannot be mislabeled as a Daytona score.

For a configured official OSWorld checkout, run one task with:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.run_osworld_makima "Complete the task in the VM" --task-id smoke-001 --runtime daytona --max-steps 15
```

`--max-steps 20` is also supported. `--runtime local` is only a host smoke
mode and must not be reported as a Daytona benchmark result.

For the `Run Continuous` benchmark on Daytona, stop a continuous run with `Ctrl+C`:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.run_osworld_makima "Complete the task in the VM" --runtime daytona --max-steps 15 --continuous --interval 5
```

Probe all five configured models first with:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.check_dashscope_models
```

The OSWorld cascade is isolated to eight Alibaba Qwen backends. The visual
models are first: `qwen3-vl-plus-2025-12-19`, `qwen3-vl-plus`, and
`qwen3-vl-flash-2025-10-15`, followed by `qwen3.8-max`, `qwen3.7-max`,
`qwen3.7-plus`, `qwen3.6-plus`, and `qwen-plus`. They use DashScope's OpenAI-compatible
`/compatible-mode/v1` international endpoint and `DASHSCOPE_API_KEY`. For a
workspace-specific key, override the endpoint with
`MAKIMA_PROVIDERS__BACKENDS__ALIBABA_QWEN_MAX__BASE_URL` and apply the same
endpoint to the other four entries; DashScope keys and endpoints must use the
same region.

## Daytona

`DaytonaRuntime` lazy-loads the optional `daytona` package and calls the SDK's
`sandbox.process.exec(...)` API. It is intentionally not created by default;
set up credentials and the VM/GUI bridge first, then create the runtime in the
benchmark runner. The Daytona dependency is already declared in the
`sandboxing` optional extra.

An OSWorld score should only be reported after the official OSWorld evaluator
has run its task setup, observation/action loop, and post-task evaluation against
the VM. The contract test is a harness/attribution check, not an OSWorld score.

## Windows host safe evaluation

When no VM is available, use the bounded Windows suite for a real Makima loop
without giving the agent destructive desktop access:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.run_windows_safe_osworld --list-tasks
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.run_windows_safe_osworld --task-id windows-files-001 --max-steps 15
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m benchmarks.run_windows_safe_osworld --task-id windows-files-002 --max-steps 15
```

These tasks borrow the v1/v2 evaluation shape—seed/reset, observation and
action loop, bounded step budget, trajectory, and executable post-task
evaluator—but are not official OSWorld tasks or scores. They use fixed,
multi-step file/data-reconciliation tasks inside `%TEMP%\makima-osworld-safe-*`.
The evaluator checks exact structured outputs (with platform-newline tolerance,
and semantic validation where formatting may vary) and rejects unexpected files. No VM,
browser, shell, registry, settings, messaging, or arbitrary process tool is
available to Makima.
