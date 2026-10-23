"""
Makima v2 — Verification Test for Step 9.5: Zero-Vision Desktop UI Automation.
Tests:
1. Tool registration & auto-generated Pydantic v2 schemas in ToolRegistry.
2. Direct thread-safe UIA inspection (inspect_app_ui) without screenshots.
3. Element matching & filtering logic.
4. UI text reading (read_ui_text).
5. Error handling when target window does not exist.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from makima.tools.registry import get_registry
from makima.tools.os.windows import list_open_windows
from makima.tools.desktop.uia import (
    inspect_app_ui,
    click_ui_element,
    read_ui_text,
    _element_to_dict,
)


class TestDesktopUIA(unittest.TestCase):

    def test_01_tool_registration(self):
        """Verify all desktop tools are decorated and present in ToolRegistry with valid JSON schemas."""
        reg = get_registry()
        reg.discover()

        expected_tools = [
            "inspect_app_ui",
            "click_ui_element",
            "set_ui_text",
            "read_ui_text",
            "send_keys_to_app",
        ]

        registered_names = [t.name for t in reg.list_tools()]
        for name in expected_tools:
            self.assertIn(name, registered_names, f"Tool '{name}' must be registered")

        # Verify schema generation
        schemas = reg.get_schemas()
        uia_schemas = [s for s in schemas if s["function"]["name"] in expected_tools]
        self.assertEqual(len(uia_schemas), 5, "All 5 desktop tools must have valid function schemas")
        print("  [PASS] Tool registration & dynamic JSON schemas verified.")

    def test_02_invalid_window_error_handling(self):
        """Verify inspecting or clicking non-existent window returns structured failure instead of crashing."""
        res_inspect = inspect_app_ui(title_query="NON_EXISTENT_WINDOW_TITLE_12345")
        self.assertFalse(res_inspect["success"])
        self.assertIn("error", res_inspect)

        res_click = click_ui_element(title_query="NON_EXISTENT_WINDOW_TITLE_12345", name="OK")
        self.assertFalse(res_click["success"])
        self.assertIn("error", res_click)

        res_read = read_ui_text(title_query="NON_EXISTENT_WINDOW_TITLE_12345")
        self.assertFalse(res_read["success"])
        self.assertIn("error", res_read)
        print("  [PASS] Non-existent window error interception verified.")

    def test_03_live_window_inspection_and_reading(self):
        """Verify live UIA inspection and text reading on an active open window."""
        open_wins = list_open_windows()
        self.assertGreater(len(open_wins), 0, "There must be at least one open window on desktop")

        # Pick first available window with a title
        target = open_wins[0]
        target_hwnd = target["hwnd"]
        target_title = target["title"]

        # Run inspect_app_ui
        res = inspect_app_ui(hwnd=target_hwnd, max_elements=20, include_empty_names=True)
        self.assertTrue(res["success"], f"UIA inspection failed: {res.get('error')}")
        self.assertEqual(res["hwnd"], target_hwnd)
        self.assertIsInstance(res.get("controls"), list)

        # Run read_ui_text on that window
        res_read = read_ui_text(hwnd=target_hwnd)
        self.assertTrue(res_read["success"], f"read_ui_text failed: {res_read.get('error')}")
        self.assertIn("total_text_blocks", res_read)
        print(f"  [PASS] Live UIA inspection on '{target_title[:30]}' verified ({res['total_controls_found']} controls found).")

    def test_04_element_to_dict_metadata(self):
        """Verify _element_to_dict produces clean zero-vision schema."""
        class MockElementInfo:
            control_type = "Button"
            automation_id = "SubmitBtn1"
            class_name = "WPFButton"

        class MockRect:
            left = 100
            top = 200
            right = 300
            bottom = 250
            def width(self): return 200
            def height(self): return 50

        class MockElement:
            element_info = MockElementInfo()
            def window_text(self): return "Submit Order"
            def rectangle(self): return MockRect()
            def is_enabled(self): return True
            def is_visible(self): return True

        d = _element_to_dict(MockElement(), depth=2)
        self.assertEqual(d["name"], "Submit Order")
        self.assertEqual(d["control_type"], "Button")
        self.assertEqual(d["automation_id"], "SubmitBtn1")
        self.assertEqual(d["class_name"], "WPFButton")
        self.assertTrue(d["enabled"])
        self.assertTrue(d["visible"])
        self.assertEqual(d["rect"]["width"], 200)
        self.assertEqual(d["depth"], 2)
        print("  [PASS] Semantic UIA element serialization verified.")


if __name__ == "__main__":
    print("=" * 75)
    print("MAKIMA v2 — STEP 9.5: ZERO-VISION UNIVERSAL DESKTOP AUTOMATION TEST")
    print("=" * 75)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDesktopUIA)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("=" * 75)
        print("ALL ZERO-VISION DESKTOP AUTOMATION TESTS PASSED (EXIT CODE 0)")
        print("=" * 75)
        sys.exit(0)
    else:
        print("=" * 75)
        print("TEST FAILURES ENCOUNTERED")
        print("=" * 75)
        sys.exit(1)
