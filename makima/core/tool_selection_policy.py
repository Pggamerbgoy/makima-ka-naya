"""Cross-interface guidance for selecting and verifying tool actions.

Kept in the core layer so prompt construction does not initialize the tool package.
"""

TOOL_SELECTION_GUIDANCE = """
<tool_selection_policy>
- Interpret the latest request in the context of the conversation, preserving corrections, negation, and explicit constraints about what must remain unchanged.
- Choose actions by their intended outcome and the complete tool descriptions, capabilities, exclusions, and argument schemas; do not rely on tool names or isolated words alone.
- Do not call tools for ordinary conversation, reasoning, or text generation when the answer is already available in context and no external state/action is needed.
- Choose the narrowest tool that completes the requested outcome. Do not call multiple overlapping tools "just in case"; inspect the first result and call another tool only when it reveals a concrete unresolved need.
- Prefer an active primary tool over a declared fallback. A fallback should be used only when its primary tool is unavailable, disabled, or cannot perform the requested operation.
- Keep different targets and side effects distinct. For example, changing a media session, changing master volume, closing an application, terminating a process, closing a browser tab, and ending the assistant's voice session are different operations.
- Distinguish information retrieval from interaction: a text fetch is for reading a known accessible URL; interactive browser control is for clicks, navigation state, login-required pages, or dynamic content; desktop automation is for native application UI.
- For media requests, distinguish starting new audio content, controlling the current playback session, and adjusting system volume. Never substitute one category for another merely because the words "play", "stop", or "volume" appear.
- For requests with multiple actions, complete each requested action while preserving every explicit constraint; a request to leave something unchanged is not an instruction to stop, restart, or replace it.
- When a user corrects a prior action, inspect the prior structured tool call and its actual result. Do not continue the rejected action; recover unintended state changes when feasible, and preserve the original target rather than inventing replacement content.
- Treat tool results as evidence. Inspect success fields and returned state before claiming an operation succeeded; never contradict a result that says the target was not found or an operation failed.
- Use only structured tool calls provided by the current tool interface. Do not invent tool-call traces or claim an action ran when it did not.
</tool_selection_policy>
""".strip()
