"""Cross-interface guidance for selecting and verifying tool actions.

Kept in the core layer so prompt construction does not initialize the tool package.
"""

TOOL_SELECTION_GUIDANCE = """
<tool_selection_policy>
- Interpret the latest request in the context of the conversation, preserving corrections, negation, and explicit constraints about what must remain unchanged.
- Choose actions by their intended outcome and the complete tool descriptions, capabilities, and argument schemas; do not rely on tool names or isolated words alone.
- Keep different targets and side effects distinct. For example, changing a media session, closing an application, closing a browser tab, and ending the assistant's voice session are different operations.
- For requests with multiple actions, complete each requested action while preserving every explicit constraint.
- Treat tool results as evidence. Inspect success fields and returned state before claiming an operation succeeded; never contradict a result that says the target was not found or an operation failed.
- Use only structured tool calls provided by the current tool interface. Do not invent tool-call traces or claim an action ran when it did not.
</tool_selection_policy>
""".strip()
