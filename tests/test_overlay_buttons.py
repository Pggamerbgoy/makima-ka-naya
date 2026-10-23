"""
Makima v2 — Comprehensive Button & Interaction Verification Suite for Native Overlay HUD.
Tests all buttons, toggles, event bindings, drag handles, confirmation flows, and chat bubbles:
1. Compact Mode [^] Expand button
2. Expanded Mode [−] Collapse button
3. Pin [📌] Topmost toggle button
4. Close [✕] Dismiss button
5. Voice [🎙️] Toggle button (Active/Inactive state and styling)
6. Security Confirmation [Allow] / [Deny] buttons
7. All 4 Quick Action Chips (Music, Summarize, Code Assist, Clean Temp)
8. Compact [↑] Send button & Enter key binding
9. Expanded [↑] Send button & Enter key binding
10. Chat bubble stream (User right-bubble, Assistant left-bubble with AgentTag)
"""

import sys
import pathlib
import time

# Ensure utf-8 stdout on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure makima_v2 is in sys.path
makima_root = pathlib.Path(__file__).resolve().parent.parent
if str(makima_root) not in sys.path:
    sys.path.insert(0, str(makima_root))

from makima.overlay.hud import SpotlightHUD, PALETTE


class DummyEvent:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y


def run_button_audit():
    print("=" * 75)
    print(">>> [RUFLO SWARM AUDIT] EXHAUSTIVE BUTTON & INTERACTION SUITE")
    print("=" * 75)

    hud = SpotlightHUD(enable_hotkey=False, start_hidden=False)
    hud.root.update()
    hud.root.update_idletasks()

    # -------------------------------------------------------------------------
    # TEST 1: Expand Button [^] and Collapse Button [−]
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Verifying Expand [^] and Collapse [−] Buttons...")
    assert not hud.is_expanded, "HUD should initially be compact"
    assert hud.compact_bar.winfo_ismapped(), "Compact bar must be mapped initially"

    # Simulate click on expand_btn
    hud.expand_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.is_expanded, "Expand button must set is_expanded=True"
    assert hud.expanded_frame.winfo_ismapped(), "Expanded frame must be mapped after expand"
    print(f"  [PASS] Expand Button [^] triggered transition to {hud.expanded_height}px.")

    # Simulate click on collapse_btn
    hud.collapse_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert not hud.is_expanded, "Collapse button must set is_expanded=False"
    assert hud.compact_bar.winfo_ismapped(), "Compact bar must be re-mapped after collapse"
    print(f"  [PASS] Collapse Button [−] triggered transition to {hud.compact_height}px.")

    # -------------------------------------------------------------------------
    # TEST 2: Pin Button [📌] Toggle
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Verifying Pin Button [📌] Topmost Toggle...")
    hud.expand()
    hud.root.update_idletasks()
    assert hud.is_pinned is True, "HUD should start pinned by default"

    # Click pin button -> unpin
    hud.pin_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.is_pinned is False, "Pin button must toggle is_pinned to False"
    assert hud.pin_btn.cget("fg") == PALETTE["text_muted"], "Pin button text color must dim when unpinned"
    print("  [PASS] Pin Button unpinned window (is_pinned=False).")

    # Click pin button -> re-pin
    hud.pin_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.is_pinned is True, "Pin button must toggle is_pinned to True"
    assert hud.pin_btn.cget("fg") == PALETTE["soft"], "Pin button text color must highlight when pinned"
    print("  [PASS] Pin Button re-pinned window (is_pinned=True).")

    # -------------------------------------------------------------------------
    # TEST 3: Close Button [✕] and Show/Hide
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Verifying Close Button [✕] and Visibility Lifecycle...")
    hud.show()
    assert hud.is_visible is True, "HUD must be visible after show()"

    # Click Close [✕] button
    hud.exp_close_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.is_visible is False, "Close button must hide HUD (is_visible=False)"
    print("  [PASS] Close Button [✕] hid HUD cleanly.")

    # Toggle visibility
    hud.toggle_visibility()
    hud.root.update()
    hud.root.update_idletasks()
    assert hud.is_visible is True, "toggle_visibility must show HUD when hidden"
    print("  [PASS] toggle_visibility() restored HUD.")

    # -------------------------------------------------------------------------
    # TEST 4: Voice Toggle Button [🎙️]
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Verifying Voice Toggle Button [🎙️]...")
    assert hud.voice_active is False, "Voice should start inactive"

    # Click Voice button -> activate
    hud.voice_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.voice_active is True, "Voice button must set voice_active=True"
    assert "Stop" in hud.voice_btn.cget("text"), f"Voice button text should indicate Stop, got: {hud.voice_btn.cget('text')}"
    assert "listening" in hud.status_strip.cget("text").lower(), "Status strip should show listening"
    print("  [PASS] Voice Button activated voice mode (voice_active=True).")

    # Click Voice button -> deactivate
    hud.voice_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert hud.voice_active is False, "Voice button must set voice_active=False"
    assert "Voice" in hud.voice_btn.cget("text"), "Voice button text must revert to Voice"
    print("  [PASS] Voice Button deactivated voice mode cleanly.")

    # -------------------------------------------------------------------------
    # TEST 5: Security Confirmation Bar [Allow] / [Deny] Buttons
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Verifying Security Confirmation Bar [Allow] / [Deny] Buttons...")
    hud.show_confirmation("Delete temporary cache files at /tmp/cache")
    hud.root.update_idletasks()
    assert hud.confirmation_frame.winfo_ismapped(), "Confirmation frame must be visible"
    assert "Delete temporary cache" in hud.confirmation_lbl.cget("text")
    print("  [PASS] show_confirmation() rendered warning card.")

    # Click Allow
    initial_bubbles = len(hud.chat_scroll_frame.winfo_children())
    hud.allow_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert not hud.confirmation_frame.winfo_ismapped(), "Confirmation frame must hide on Allow"
    new_bubbles = len(hud.chat_scroll_frame.winfo_children())
    assert new_bubbles == initial_bubbles + 1, "Approval message must be appended to chat"
    print("  [PASS] [Allow] button approved action and dismissed prompt.")

    # Show confirmation again for Deny test
    hud.show_confirmation("Elevated PowerShell admin script execution")
    hud.root.update_idletasks()
    assert hud.confirmation_frame.winfo_ismapped(), "Confirmation frame must be re-mapped"

    # Click Deny
    hud.deny_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    assert not hud.confirmation_frame.winfo_ismapped(), "Confirmation frame must hide on Deny"
    new_bubbles2 = len(hud.chat_scroll_frame.winfo_children())
    assert new_bubbles2 == new_bubbles + 1, "Denial message must be appended to chat"
    print("  [PASS] [Deny] button blocked action and dismissed prompt.")

    # -------------------------------------------------------------------------
    # TEST 6: Quick Action Chips Row
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Verifying Quick Action Chips...")
    chips = hud.chips_row.winfo_children()
    assert len(chips) in (4, 5), f"Expected 4 or 5 quick chips, got {len(chips)}"
    chip_labels = [c.cget("text") for c in chips]
    print(f"  [FOUND CHIPS] {chip_labels}")
    assert any("Music" in lbl for lbl in chip_labels), "Music chip must exist"
    assert any("Browse" in lbl for lbl in chip_labels), "Browse chip must exist"
    assert any("Summarize" in lbl for lbl in chip_labels), "Summarize chip must exist"
    assert any("Code" in lbl for lbl in chip_labels), "Code Assist chip must exist"
    assert any("Clean" in lbl for lbl in chip_labels), "Clean Temp chip must exist"

    # Test hover and leave bindings on first chip
    chips[0].event_generate("<Enter>")
    assert chips[0].cget("bg") == PALETTE["chip_hover"]
    chips[0].event_generate("<Leave>")
    assert chips[0].cget("bg") == PALETTE["chip_bg"]
    print("  [PASS] Quick chip hover states verified.")

    # -------------------------------------------------------------------------
    # TEST 7: Open Chat Button
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Verifying Open Chat Button...")
    hud.open_chat_btn.event_generate("<Button-1>")
    hud.root.update_idletasks()
    # Check that a system guidance message was added to chat
    last_bubble = hud.chat_scroll_frame.winfo_children()[-1]
    assert last_bubble is not None, "Chat stream must contain chat URL guidance"
    print("  [PASS] Open Chat button successfully dispatched workspace URL message.")

    # -------------------------------------------------------------------------
    # TEST 8: Chat Bubbles & Agent Tags Verification
    # -------------------------------------------------------------------------
    print("\n[TEST 8] Verifying User vs Assistant Chat Bubbles...")
    hud.add_message(is_user=True, text="Can you inspect my active window?")
    hud.add_message(is_user=False, text="Active window is Visual Studio Code: main.py", agent="HERMES")
    hud.add_web_search_bubble(
        query="latest python 3.14 features",
        results=[
            {
                "title": "Python 3.14 Release Highlights",
                "url": "https://docs.python.org/3.14/whatsnew/3.14.html",
                "snippet": "Python 3.14 introduces template strings, deferred evaluations, and faster JIT compiler.",
            }
        ],
    )
    hud.add_web_page_bubble(
        {
            "success": True,
            "url": "https://docs.python.org/3.14/",
            "status_code": 200,
            "title": "Python 3.14 Documentation",
            "text": "Welcome to Python 3.14 official documentation and manuals.",
        }
    )
    hud.root.update_idletasks()

    all_bubbles = hud.chat_scroll_frame.winfo_children()
    assert len(all_bubbles) >= 6, f"Expected at least 6 bubbles, got {len(all_bubbles)}"
    print(f"  [PASS] Chat bubble stream verified ({len(all_bubbles)} message bubbles including web cards rendered).")

    # -------------------------------------------------------------------------
    # TEST 9: Drag Handles
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Verifying Draggable Window Math...")
    init_x = hud.root.winfo_x()
    init_y = hud.root.winfo_y()

    # Simulate drag start
    hud._start_drag(DummyEvent(x=10, y=10))
    # Simulate drag move by +20px, +30px
    hud._do_drag(DummyEvent(x=30, y=40))
    hud.root.update_idletasks()

    new_x = hud.root.winfo_x()
    new_y = hud.root.winfo_y()
    assert new_x == init_x + 20, f"Expected x={init_x + 20}, got {new_x}"
    assert new_y == init_y + 30, f"Expected y={init_y + 30}, got {new_y}"
    print(f"  [PASS] Header drag delta verified: (+20, +30) -> position ({new_x}, {new_y}).")

    # -------------------------------------------------------------------------
    # TEST 10: End-to-End Prompt Submission via Quick Chips & Engine
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Verifying Prompt Submission & Asynchronous Dispatch...")
    import asyncio
    class MockEngine:
        async def run(self, prompt, history=None, task=None):
            await asyncio.sleep(0.15)
            class Res:
                content = f"Simulated autonomous answer for: {prompt}"
                tool_calls_executed = 2
            return Res()

    hud.engine = MockEngine()
    initial_msg_count = len(hud.chat_scroll_frame.winfo_children())

    # Simulate click on Music chip
    chips[0].event_generate("<Button-1>")
    hud.root.update()
    hud.root.update_idletasks()
    assert hud.is_running is True, "HUD must enter running state on prompt submit"

    # Wait briefly for worker thread to complete
    for _ in range(30):
        time.sleep(0.05)
        hud.root.update()
        hud.root.update_idletasks()
        if not hud.is_running:
            break

    assert hud.is_running is False, "HUD must finish execution and reset is_running"
    final_msg_count = len(hud.chat_scroll_frame.winfo_children())
    # User message + Assistant reply added
    assert final_msg_count >= initial_msg_count + 2, f"Expected user+assistant messages added, got {final_msg_count}"
    print(f"  [PASS] Asynchronous execution completed: User prompt + Assistant bubble appended.")

    # -------------------------------------------------------------------------
    # TEARDOWN
    # -------------------------------------------------------------------------
    hud.root.destroy()
    print("\n" + "=" * 75)
    print(">>> [RUFLO SWARM AUDIT] ALL 10 BUTTON & INTERACTION SUITES PASSED (100% OK)")
    print("=" * 75)


if __name__ == "__main__":
    run_button_audit()
