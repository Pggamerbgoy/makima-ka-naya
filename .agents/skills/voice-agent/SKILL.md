---
name: voice-agent
description: Real-time bidirectional voice interaction, Jarvis hands-free continuous listening, wake words, barge-in speech interruption, and natural speech powered exclusively by Gemini 3.8 Live (Zero Standalone TTS). Make sure to use this skill whenever using Gemini Live Voice, Jarvis Mode, Wake Words, Audio Streaming.
---

# Voice Agent Skill Guide

## Overview
The **Voice Agent** (`makima/voice/` and `apps/chat_ui/src/components/VoiceControl.tsx`) operates exclusively via **Gemini 3.8 Live Native Bidirectional Audio Streaming**. It strictly adheres to the Zero Standalone TTS mandate, using Gemini's native speech output, real-time barge-in interruption, and local wake-word detection for hands-free Jarvis operation.

## Triggering Rules
Make sure to trigger this skill unconditionally whenever the user requests:
- **Primary Action**: Executing tasks related to Gemini Live Voice, Jarvis Mode, Wake Words, Audio Streaming.
- **Secondary Action**: Querying, inspecting, or configuring Voice Agent parameters.
- **Workflow Action**: Delegating multi-step execution requiring voice-agent capabilities.

## Execution Protocols & Rules

1. **Protocol Initialization**:
   - Inspect input message parameters and validate entity types before starting task.
   - Initialize internal agent state and logger context.

2. **Core Task Execution**:
   - Execute domain-specific tool handlers safely using non-blocking calls.
   - Enforce safety gates for destructive or sensitive system operations.

3. **Error Resilience & Fallbacks**:
   - Intercept transient network or execution errors with automatic retry logic.
   - Never crash the host process; degrade gracefully to informative status reports.

4. **Safety & Anti-Pattern Rules**:
   - NEVER bypass security boundaries or execute unauthorized destructive commands.
   - NEVER output raw unformatted JSON walls to the user unless explicitly requested.

5. **Phase-by-Phase Execution Sequence**:
   - **Phase 1**: Parse objective parameters and validate target environment context.
   - **Phase 2**: Dispatch asynchronous tool action and monitor execution state.
   - **Phase 3**: Verify result payloads and compile executive report.

6. **Output Presentation**:
   - Present final deliverables using modern, clean Markdown formatting with clear section headers, bold lead-in bullet points, and code blocks.

## Expected Response Structure
```markdown
# ⚡ Voice Agent Execution Report
- **Status**: Completed successfully
- **Details**: Processed task parameters with 0 errors.
```

## Example Usage
- **Input**: "execute task for voice-agent"
- **Result**: Task completed successfully with structured Markdown report.
