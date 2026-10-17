---
trigger: always_on
description: Mandatory Ruflo Autonomous Execution Loop (Zero-Key Swarm Pipeline: Coder -> Auto-Tester -> Auto-Auditor -> Consensus)
---

# 🐝 Mandatory Ruflo Autonomous Multi-Agent Execution Loop

> **Trigger**: Whenever the agent writes, edits, or refactors any implementation code in `makima_v2`.  
> **Golden Invariant**: **NEVER STOP AFTER WRITING CODE.** Do not ask the user for permission to test or audit. Execute the full loop autonomously in the same turn.

---

## 🔁 The 4-Stage Autonomous Chain

Whenever a code implementation or fix is performed, the agent must transition through the 4 stages in strict order:

```
[ROLE: Coder] ──(Write Code)──► [ROLE: Auto-Tester] ──(Run Tests)──► [ROLE: Auto-Auditor] ──(Scan & Review)──► [ROLE: Lead/Consensus]
```

### Stage 1: `[ROLE: Coder]`
- Writes or modifies the target module/file using `write_to_file` or `replace_file_content`.
- Ensures zero hardcoded paths and dynamic configuration.

### Stage 2: `[ROLE: Auto-Tester]` (MANDATORY IMMEDIATE EXECUTION)
- **Do not stop here!** Immediately dispatch the test or verification script via `run_command`:
  ```powershell
  python tests/verify_<module>.py
  # or pytest tests/test_<module>.py
  ```
- **Self-Healing Loop**: If tests fail:
  - Do not prompt the user.
  - Read the traceback and stderr.
  - Switch back to `[ROLE: Coder]` to patch the issue immediately.
  - Re-run the tests until green.

### Stage 3: `[ROLE: Auto-Auditor & Security Reviewer]`
- Once tests pass, run the automated swarm pipeline runner or audit checks:
  ```powershell
  python .agents/ruflo_swarm/swarm_pipeline.py --run --target <file_path> --test-cmd "<test_command>"
  ```
- Verifies:
  1. **AST Complexity**: No function cyclomatic complexity > 15.
  2. **Security & PII**: Scanned for leaked tokens, raw credentials, or command injection.
  3. **Caller-Callee Integrity**: Cross-checks all callers in the codebase to prevent runtime `TypeError` / `KeyError`.

### Stage 4: `[ROLE: Lead / Raft Consensus]`
- Verifies consensus receipt logged to `.swarm/pipeline_ledger.jsonl`.
- Presents the final executive summary to the user with test duration, audit status, and caller compatibility.
