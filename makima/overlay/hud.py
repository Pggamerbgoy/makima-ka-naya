"""
Makima v2 — Native Windows Spotlight HUD & Desktop Overlay Window.
100% Windows Native GUI (Win32, DWM, Ctypes, Tkinter Canvas). Zero HTML / Browser.

Directly modelled after Makima v1 Native Slint Overlay (apps/native_overlay/ui/overlay.slint)
with v2 modern customizations:
- Exact Old Makima Color Palette & Visual Architecture
- Dual Display Mode:
  1. Compact Pill (440px x 56px): Rounded pill with M-badge, status dot, preview text, inline reply input, send button, expand toggle
  2. Expanded Panel (440px x 580px): Chat bubble conversation history, agent tags, thinking dots, confirmation bar, quick chips, tool execution DAG, voice/action bar
- Win32 Acrylic Blur Behind (ACCENT_ENABLE_ACRYLICBLURBEHIND = 4) & DWM Dark Mode
- Global Hotkey Toggle (Ctrl+Space) & Esc Dismiss
"""

from __future__ import annotations

import asyncio
import ctypes
import inspect
import logging
import math
import queue
import re
import sys
import threading
import time
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional
import webbrowser

try:
    import psutil
    import win32con
    import win32gui
    import win32process
except ImportError:
    psutil = None
    win32con = None
    win32gui = None
    win32process = None


from makima.core.engine import HermesAgentEngine
from makima.tools.browser.fetcher import fetch_web_page, search_web
from makima.tools.registry import ToolRegistry, get_registry

URL_RE = re.compile(
    r"^(?:https?://)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?::\d+)?(?:/[^\s]*)?$",
    re.IGNORECASE,
)
SEARCH_RE = re.compile(
    r"^(?:search(?:\s+(?:the\s+)?web)?(?:\s+for)?|browse|find\s+online|google|ddg)\s*[:\-]?\s*(.+)$",
    re.IGNORECASE,
)

logger = logging.getLogger("makima.overlay")

# Enable Per-Monitor High DPI Awareness on Windows (prevents bitmap scaling blur)
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Color Palette: Exact Old Makima Slint Theme (Pal in overlay.slint)
# -----------------------------------------------------------------------------
PALETTE: Dict[str, str] = {
    "bg_base": "#0D0B18",          # Deep Obsidian Space (#0d0b18)
    "surface": "#161228",          # Card Surface (#161228)
    "surface_card": "#18152C",     # Elevated Container (#18152c)
    "input_bg": "#1D1A30",         # Inset Input Container (#1d1a30)
    "border": "#272040",           # Crisp Hairline Boundary (#272040)
    "border_focus": "#6D28D9",     # Highlight Violet (#6d28d9)
    "hi": "#6D28D9",               # High Purple Accent (#6d28d9)
    "accent": "#7C3AED",           # Core Violet Accent (#7c3aed)
    "soft": "#A78BFA",             # Soft Violet Secondary (#a78bfa)
    "text_primary": "#EDE9FE",     # Bright Foreground (#ede9fe)
    "text_secondary": "#9C96B8",   # Mid Foreground (#9c96b8)
    "text_muted": "#4E4769",       # Low Foreground / Subdued (#4e4769)
    "text_hint": "#4E4769",        # Placeholder
    "green": "#34D399",            # Green Status / Pal.green
    "success": "#34D399",          # Green Status (#34d399)
    "warning": "#F59E0B",          # Warning Amber
    "red": "#F87171",              # Voice / Error Crimson (#f87171)
    # Chat Bubble Colors
    "user_bg": "#2D1B69",          # User Bubble Background (#2d1b69)
    "user_br": "#4C2D9C",          # User Bubble Border (#4c2d9c)
    "asst_bg": "#18152C",          # Assistant Bubble Background (#18152c)
    "asst_br": "#272040",          # Assistant Bubble Border (#272040)
    # Security Confirmation Bar Colors
    "warn_bg": "#1C1007",          # Warning Card Background (#1c1007)
    "warn_br": "#92400E",          # Warning Card Border (#92400e)
    "warn_fg": "#FDE68A",          # Warning Card Text (#fde68a)
    # Quick Chips & Action Buttons
    "chip_bg": "#1C1834",
    "chip_br": "#352A5A",
    "chip_hover": "#2B2446",
}


class SpotlightHUD:
    """
    Native Windows Spotlight HUD Overlay.
    Faithful recreation of Makima v1 Slint HUD with v2 enhancements.
    """

    def __init__(
        self,
        engine: Optional[HermesAgentEngine] = None,
        registry: Optional[ToolRegistry] = None,
        width: int = 440,
        enable_hotkey: bool = True,
        start_hidden: bool = False,
    ) -> None:
        self.width = width
        self.compact_height = 56
        self.expanded_height = 615
        self.is_expanded = False
        self.is_visible = True
        self.is_running = False
        self.is_pinned = True
        self.voice_active = False
        self._is_alive = True
        self._pulse_phase = 0.0

        # Screen-Aware Quick AI Bar Context State
        self.target_hwnd: Optional[int] = None
        self.target_title: str = ""
        self.target_app_name: str = ""
        self.captured_selection: str = ""
        self._last_assistant_output: str = ""
        self._auto_paste_on_finish: bool = False
        self._voice_controller: Optional[Any] = None

        self.engine = engine
        self.registry = registry or get_registry(auto_discover=True)
        self.conversation_history: List[Dict[str, Any]] = []

        # 1. Initialize Tkinter Root
        self.root = tk.Tk()
        self.root.title("Makima")
        self.root.configure(bg=PALETTE["bg_base"])

        # 2. Window Chrome & Geometry
        self.root.overrideredirect(True)        # Borderless floating card
        self.root.attributes("-topmost", True)  # Always on top

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.pos_x = (self.screen_w - self.width) // 2
        self.pos_y = int(self.screen_h * 0.12)

        self.root.geometry(f"{self.width}x{self.compact_height}+{self.pos_x}+{self.pos_y}")

        # 3. Apply Native Windows DWM & Acrylic Glass
        self._apply_dwm_styling()

        # 4. Draggable Window Behavior
        self._drag_data = {"x": 0, "y": 0}

        # 5. Build Native UI Hierarchy (Compact Pill + Expanded Panel)
        self._build_ui()

        # 6. Global Key Bindings
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<FocusOut>", self._on_focus_out)

        # 7. Ambient Pulsing Animations (Status Dot & Equalizer)
        self._start_ambient_animations()

        # 8. Thread-Safe UI Update Queue
        self._dispatch_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._process_dispatch_queue()

        # 9. Background Hotkey Listener (Ctrl+Space)
        self._hotkey_listener = None
        if enable_hotkey:
            self._start_global_hotkey()

        if start_hidden:
            self.hide()
        else:
            self.show()

    # -------------------------------------------------------------------------
    # Native Windows DWM Window Styling & Acrylic Glass Backdrop
    # -------------------------------------------------------------------------
    def _apply_dwm_styling(self) -> None:
        """Applies native Windows 11 Acrylic blur, rounded corners, and dark mode via Win32 DWM."""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

            # 1. Native Win32 Extended Styles: TOPMOST + TOOLWINDOW (prevents Alt-Tab clutter)
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            WS_EX_TOOLWINDOW = 0x00000080
            cur_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur_style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)

            # 2. DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            dark_mode = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
            )

            # 3. DWMWA_WINDOW_CORNER_PREFERENCE = 33 (2 = DWMWCP_ROUND)
            round_pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(round_pref), ctypes.sizeof(round_pref)
            )

            # 4. DWMWA_BORDER_COLOR = 34 (Hairline violet boundary)
            border_color = ctypes.c_int(0x00402027)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color)
            )

            # 5. Native Windows Acrylic Blur Behind (SetWindowCompositionAttribute)
            class AccentPolicy(ctypes.Structure):
                _fields_ = [
                    ("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_uint),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_uint),
                ]

            class WindowCompositionAttributeData(ctypes.Structure):
                _fields_ = [
                    ("Attribute", ctypes.c_int),
                    ("Data", ctypes.POINTER(AccentPolicy)),
                    ("SizeOfData", ctypes.c_uint),
                ]

            # ACCENT_ENABLE_ACRYLICBLURBEHIND = 4, Translucent Makima Obsidian-Violet 0xCC181222
            policy = AccentPolicy(4, 0, 0xCC181222, 0)
            data = WindowCompositionAttributeData(19, ctypes.pointer(policy), ctypes.sizeof(policy))
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))

            # 6. Extend DWM frame into client area for native Windows 11 drop shadow
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = MARGINS(-1, -1, -1, -1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        except Exception as exc:
            logger.debug("Native Windows DWM/Acrylic styling notice: %s", exc)

    # -------------------------------------------------------------------------
    # UI Hierarchy & Component Construction
    # -------------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Outer Frame
        self.outer_frame = tk.Frame(
            self.root,
            bg=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        self.outer_frame.pack(fill=tk.BOTH, expand=True)

        # Context Chip Frame (Screen-Aware Quick AI Bar)
        self.context_chip_frame = tk.Frame(
            self.outer_frame,
            bg=PALETTE["chip_bg"],
            highlightbackground=PALETTE["chip_br"],
            highlightthickness=1,
            padx=8,
            pady=3,
        )
        self.context_chip_lbl = tk.Label(
            self.context_chip_frame,
            text="📄 Context",
            font=("Segoe UI", 8),
            fg=PALETTE["soft"],
            bg=PALETTE["chip_bg"],
            anchor=tk.W,
        )
        self.context_chip_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.context_chip_close = tk.Label(
            self.context_chip_frame,
            text="✕",
            font=("Segoe UI", 8, "bold"),
            fg=PALETTE["text_muted"],
            bg=PALETTE["chip_bg"],
            cursor="hand2",
            padx=4,
        )
        self.context_chip_close.pack(side=tk.RIGHT)
        self.context_chip_close.bind("<Button-1>", lambda e: self.clear_context())
        self.context_chip_close.bind("<Enter>", lambda e: self.context_chip_close.configure(fg=PALETTE["red"]))
        self.context_chip_close.bind("<Leave>", lambda e: self.context_chip_close.configure(fg=PALETTE["text_muted"]))

        # ---------------------------------------------------------------------
        # 1. Compact Mode Pill (When compact == True)
        # ---------------------------------------------------------------------
        self.compact_bar = tk.Frame(self.outer_frame, bg=PALETTE["surface"])
        self.compact_bar.pack(fill=tk.X)
        self.compact_bar.bind("<Button-1>", self._start_drag)
        self.compact_bar.bind("<B1-Motion>", self._do_drag)

        # M Logo Badge (Makima v1 signature)
        self.m_badge = tk.Label(
            self.compact_bar,
            text=" M ",
            font=("Segoe UI", 11, "bold"),
            fg="#FFFFFF",
            bg=PALETTE["accent"],
            padx=2,
            pady=1,
            cursor="hand2",
        )
        self.m_badge.pack(side=tk.LEFT, padx=(2, 6))
        self.m_badge.bind("<Button-1>", self._start_drag)
        self.m_badge.bind("<B1-Motion>", self._do_drag)

        # Status Dot Canvas (Green connected / Red voice pulse)
        self.status_dot_canvas = tk.Canvas(
            self.compact_bar,
            width=10,
            height=10,
            bg=PALETTE["surface"],
            highlightthickness=0,
            bd=0,
        )
        self.status_dot_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self.status_dot_canvas.bind("<Button-1>", self._start_drag)
        self.status_dot_canvas.bind("<B1-Motion>", self._do_drag)

        # Status / Preview Text
        self.preview_lbl = tk.Label(
            self.compact_bar,
            text="Makima AI",
            font=("Segoe UI", 9, "bold"),
            fg=PALETTE["text_secondary"],
            bg=PALETTE["surface"],
            width=9,
            anchor=tk.W,
        )
        self.preview_lbl.pack(side=tk.LEFT, padx=(0, 6))
        self.preview_lbl.bind("<Button-1>", self._start_drag)
        self.preview_lbl.bind("<B1-Motion>", self._do_drag)

        # Inline Reply Input Capsule
        self.compact_input_box = tk.Frame(
            self.compact_bar,
            bg=PALETTE["input_bg"],
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["hi"],
            highlightthickness=1,
            padx=8,
            pady=3,
        )
        self.compact_input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.compact_entry_var = tk.StringVar(value="Reply to Makima...")
        self._compact_has_placeholder = True

        self.compact_entry = tk.Entry(
            self.compact_input_box,
            textvariable=self.compact_entry_var,
            font=("Segoe UI", 9),
            fg=PALETTE["text_muted"],
            bg=PALETTE["input_bg"],
            insertbackground=PALETTE["soft"],
            relief=tk.FLAT,
            bd=0,
        )
        self.compact_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.compact_entry.bind("<Return>", lambda e: self._on_compact_submit())
        self.compact_entry.bind("<Shift-Return>", lambda e: self._on_shift_return_compact())
        self.compact_entry.bind("<FocusIn>", self._on_compact_focus_in)
        self.compact_entry.bind("<FocusOut>", self._on_compact_focus_out)
        self.compact_entry.bind("<Key>", self._on_compact_key)

        # Send Button [↑]
        self.compact_send_btn = tk.Label(
            self.compact_input_box,
            text="↑",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg=PALETTE["hi"],
            padx=6,
            pady=1,
            cursor="hand2",
        )
        self.compact_send_btn.pack(side=tk.RIGHT)
        self.compact_send_btn.bind("<Button-1>", lambda e: self._on_compact_submit())
        self.compact_send_btn.bind("<Enter>", lambda e: self.compact_send_btn.configure(bg=PALETTE["accent"]))
        self.compact_send_btn.bind("<Leave>", lambda e: self.compact_send_btn.configure(bg=PALETTE["hi"]))

        # Expand Button [▾]
        self.expand_btn = tk.Label(
            self.compact_bar,
            text="▾",
            font=("Segoe UI", 12, "bold"),
            fg=PALETTE["soft"],
            bg=PALETTE["surface"],
            cursor="hand2",
            padx=4,
        )
        self.expand_btn.pack(side=tk.RIGHT)
        self.expand_btn.bind("<Button-1>", lambda e: self.expand())
        self.expand_btn.bind("<Enter>", lambda e: self.expand_btn.configure(fg=PALETTE["text_primary"]))
        self.expand_btn.bind("<Leave>", lambda e: self.expand_btn.configure(fg=PALETTE["soft"]))

        # ---------------------------------------------------------------------
        # 2. Expanded Mode Panel (When compact == False)
        # ---------------------------------------------------------------------
        self.expanded_frame = tk.Frame(self.outer_frame, bg=PALETTE["surface"])

        # Header Row (Drag region)
        self.exp_header = tk.Frame(self.expanded_frame, bg=PALETTE["surface"])
        self.exp_header.pack(fill=tk.X, pady=(0, 6))
        self.exp_header.bind("<Button-1>", self._start_drag)
        self.exp_header.bind("<B1-Motion>", self._do_drag)

        # M Badge in Header
        self.exp_m_badge = tk.Label(
            self.exp_header,
            text=" M ",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg=PALETTE["accent"],
            padx=2,
            pady=1,
            cursor="hand2",
        )
        self.exp_m_badge.pack(side=tk.LEFT, padx=(0, 8))
        self.exp_m_badge.bind("<Button-1>", self._start_drag)
        self.exp_m_badge.bind("<B1-Motion>", self._do_drag)

        # Title: "Makima"
        self.exp_title = tk.Label(
            self.exp_header,
            text="Makima",
            font=("Segoe UI", 11, "bold"),
            fg=PALETTE["text_primary"],
            bg=PALETTE["surface"],
        )
        self.exp_title.pack(side=tk.LEFT)
        self.exp_title.bind("<Button-1>", self._start_drag)
        self.exp_title.bind("<B1-Motion>", self._do_drag)

        # Active Agent Tag Pill (e.g. "Yukino")
        self.agent_tag = tk.Label(
            self.exp_header,
            text="Yukino",
            font=("Segoe UI", 8, "bold"),
            fg=PALETTE["soft"],
            bg=PALETTE["input_bg"],
            padx=6,
            pady=1,
        )
        self.agent_tag.pack(side=tk.LEFT, padx=(8, 0))

        # Close [✕] Button
        self.exp_close_btn = tk.Label(
            self.exp_header,
            text="✕",
            font=("Segoe UI", 10),
            fg=PALETTE["text_muted"],
            bg=PALETTE["surface"],
            cursor="hand2",
            padx=4,
        )
        self.exp_close_btn.pack(side=tk.RIGHT)
        self.exp_close_btn.bind("<Button-1>", lambda e: self.hide())
        self.exp_close_btn.bind("<Enter>", lambda e: self.exp_close_btn.configure(fg=PALETTE["text_primary"]))
        self.exp_close_btn.bind("<Leave>", lambda e: self.exp_close_btn.configure(fg=PALETTE["text_muted"]))

        # Collapse [-] Button
        self.collapse_btn = tk.Label(
            self.exp_header,
            text="−",
            font=("Segoe UI", 11, "bold"),
            fg=PALETTE["text_muted"],
            bg=PALETTE["surface"],
            cursor="hand2",
            padx=6,
        )
        self.collapse_btn.pack(side=tk.RIGHT)
        self.collapse_btn.bind("<Button-1>", lambda e: self.collapse())
        self.collapse_btn.bind("<Enter>", lambda e: self.collapse_btn.configure(fg=PALETTE["text_primary"]))
        self.collapse_btn.bind("<Leave>", lambda e: self.collapse_btn.configure(fg=PALETTE["text_muted"]))

        # Pin [📌] Button
        self.pin_btn = tk.Label(
            self.exp_header,
            text="📌",
            font=("Segoe UI", 9),
            fg=PALETTE["soft"],
            bg=PALETTE["surface"],
            cursor="hand2",
            padx=4,
        )
        self.pin_btn.pack(side=tk.RIGHT, padx=4)
        self.pin_btn.bind("<Button-1>", lambda e: self._toggle_pin())

        # Status Strip (Subdued status line from Old Makima)
        self.status_strip = tk.Label(
            self.expanded_frame,
            text="Connected to Makima Core",
            font=("Segoe UI", 8),
            fg=PALETTE["text_muted"],
            bg=PALETTE["surface"],
            anchor=tk.W,
        )
        self.status_strip.pack(fill=tk.X, pady=(0, 4))

        # Thin Hairline Divider (Pal.border)
        self.divider = tk.Frame(self.expanded_frame, height=1, bg=PALETTE["border"])
        self.divider.pack(fill=tk.X, pady=(0, 6))

        # Quick Action Chips Row (Modern Makima Customization)
        self.chips_row = tk.Frame(self.expanded_frame, bg=PALETTE["surface"])
        self.chips_row.pack(fill=tk.X, pady=(0, 6))
        self._build_quick_chips()

        # Autonomous Step DAG Tracker Container (Pillar 2 / SOTA UX)
        self.dag_container = tk.Frame(
            self.expanded_frame,
            bg=PALETTE["surface_card"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        self.dag_steps_frame = tk.Frame(self.dag_container, bg=PALETTE["surface_card"])
        self.dag_steps_frame.pack(fill=tk.X)

        # Scrollable Chat History Stream (Real User & Assistant Bubbles)
        self.chat_container = tk.Frame(
            self.expanded_frame,
            bg=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        self.chat_container.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self.chat_canvas = tk.Canvas(
            self.chat_container,
            bg=PALETTE["surface"],
            highlightthickness=0,
            bd=0,
        )
        self.chat_scrollbar = tk.Scrollbar(
            self.chat_container, orient=tk.VERTICAL, command=self.chat_canvas.yview
        )
        self.chat_scroll_frame = tk.Frame(self.chat_canvas, bg=PALETTE["surface"])

        self.chat_scroll_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all")),
        )
        self.chat_window_id = self.chat_canvas.create_window(
            (0, 0), window=self.chat_scroll_frame, anchor="nw", width=self.width - 44
        )

        self.chat_canvas.configure(yscrollcommand=self.chat_scrollbar.set)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Output text backup widget for test compatibility
        self.output_text = tk.Text(self.expanded_frame, height=1)

        # Thinking Dots Indicator (Staggered 3-pulse dots)
        self.thinking_frame = tk.Frame(self.expanded_frame, bg=PALETTE["surface"])
        self.thinking_dots_canvas = tk.Canvas(
            self.thinking_frame, width=32, height=12, bg=PALETTE["surface"], highlightthickness=0
        )
        self.thinking_lbl = tk.Label(
            self.thinking_frame,
            text="Thinking...",
            font=("Segoe UI", 8),
            fg=PALETTE["soft"],
            bg=PALETTE["surface"],
        )
        self.thinking_dots_canvas.pack(side=tk.LEFT)
        self.thinking_lbl.pack(side=tk.LEFT, padx=4)

        # Security Confirmation Bar (Old Makima Warning / Allow / Deny)
        self.confirmation_frame = tk.Frame(
            self.expanded_frame,
            bg=PALETTE["warn_bg"],
            highlightbackground=PALETTE["warn_br"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        self.confirmation_lbl = tk.Label(
            self.confirmation_frame,
            text="! Action requires approval",
            font=("Segoe UI", 8),
            fg=PALETTE["warn_fg"],
            bg=PALETTE["warn_bg"],
            anchor=tk.W,
            wraplength=260,
        )
        self.confirmation_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.allow_btn = tk.Label(
            self.confirmation_frame,
            text="Allow",
            font=("Segoe UI", 8, "bold"),
            fg="#86EFAC",
            bg="#183218",
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.allow_btn.pack(side=tk.RIGHT, padx=2)
        self.allow_btn.bind("<Button-1>", lambda e: self._approve_action())

        self.deny_btn = tk.Label(
            self.confirmation_frame,
            text="Deny",
            font=("Segoe UI", 8, "bold"),
            fg="#FCA5A5",
            bg="#321818",
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.deny_btn.pack(side=tk.RIGHT, padx=2)
        self.deny_btn.bind("<Button-1>", lambda e: self._reject_action())

        # Expanded Text Input Rectangle
        self.exp_input_box = tk.Frame(
            self.expanded_frame,
            bg=PALETTE["input_bg"],
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["hi"],
            highlightthickness=1,
            padx=10,
            pady=4,
        )
        self.exp_input_box.pack(fill=tk.X, pady=(0, 6))

        self.exp_entry_var = tk.StringVar(value="Ask Makima anything...")
        self._exp_has_placeholder = True

        self.exp_entry = tk.Entry(
            self.exp_input_box,
            textvariable=self.exp_entry_var,
            font=("Segoe UI", 10),
            fg=PALETTE["text_muted"],
            bg=PALETTE["input_bg"],
            insertbackground=PALETTE["soft"],
            relief=tk.FLAT,
            bd=0,
        )
        self.exp_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.exp_entry.bind("<Return>", lambda e: self._on_exp_submit())
        self.exp_entry.bind("<Shift-Return>", lambda e: self._on_shift_return_exp())
        self.exp_entry.bind("<FocusIn>", self._on_exp_focus_in)
        self.exp_entry.bind("<FocusOut>", self._on_exp_focus_out)
        self.exp_entry.bind("<Key>", self._on_exp_key)

        self.exp_send_btn = tk.Label(
            self.exp_input_box,
            text="↑",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg=PALETTE["hi"],
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.exp_send_btn.pack(side=tk.RIGHT)
        self.exp_send_btn.bind("<Button-1>", lambda e: self._on_exp_submit())
        self.exp_send_btn.bind("<Enter>", lambda e: self.exp_send_btn.configure(bg=PALETTE["accent"]))
        self.exp_send_btn.bind("<Leave>", lambda e: self.exp_send_btn.configure(bg=PALETTE["hi"]))

        # Action Row (Voice Toggle & Open Chat Button from Old Makima)
        self.action_row = tk.Frame(self.expanded_frame, bg=PALETTE["surface"])
        self.action_row.pack(fill=tk.X, pady=(0, 4))

        self.voice_btn = tk.Label(
            self.action_row,
            text="🎙️ Voice",
            font=("Segoe UI", 8, "bold"),
            fg=PALETTE["soft"],
            bg=PALETTE["chip_bg"],
            highlightbackground=PALETTE["chip_br"],
            highlightthickness=1,
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self.voice_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.voice_btn.bind("<Button-1>", lambda e: self._toggle_voice())

        self.open_chat_btn = tk.Label(
            self.action_row,
            text="💬 Open Chat",
            font=("Segoe UI", 8, "bold"),
            fg=PALETTE["soft"],
            bg=PALETTE["chip_bg"],
            highlightbackground=PALETTE["chip_br"],
            highlightthickness=1,
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self.open_chat_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self.open_chat_btn.bind("<Button-1>", lambda e: self._open_chat())

        # Footer Shortcuts Bar
        self.footer_bar = tk.Frame(self.expanded_frame, bg=PALETTE["surface"])
        self.footer_bar.pack(fill=tk.X, pady=(2, 0))

        self.footer_shortcuts = tk.Label(
            self.footer_bar,
            text="[Ctrl+Space] Toggle  •  [Shift+⏎] Paste in App  •  [Esc] Dismiss  •  [⏎] Send",
            font=("Consolas", 7),
            fg=PALETTE["text_muted"],
            bg=PALETTE["surface"],
        )
        self.footer_shortcuts.pack(side=tk.RIGHT)

        # Initial Welcome Message
        self.add_message(is_user=False, text="How can I help you?", agent="Makima")

    def _build_quick_chips(self) -> None:
        chips = [
            ("🎵 Music", "Play Lo-Fi chill beats on YouTube"),
            ("🌐 Browse", "Search the web for latest AI news and summarize top results"),
            ("📑 Summarize", "Inspect active window and summarize content"),
            ("💻 Code Assist", "Analyze current code and suggest optimization"),
            ("⚡ Clean Temp", "Scan and safely clean system temp files"),
        ]
        for label, query in chips:
            chip = tk.Label(
                self.chips_row,
                text=label,
                font=("Segoe UI", 8, "bold"),
                fg=PALETTE["soft"],
                bg=PALETTE["chip_bg"],
                highlightbackground=PALETTE["chip_br"],
                highlightthickness=1,
                padx=8,
                pady=2,
                cursor="hand2",
            )
            chip.pack(side=tk.LEFT, padx=(0, 4))
            chip.bind("<Button-1>", lambda e, q=query: self._submit_prompt(q))
            chip.bind("<Enter>", lambda e, c=chip: c.configure(bg=PALETTE["chip_hover"], fg="#FFFFFF"))
            chip.bind("<Leave>", lambda e, c=chip: c.configure(bg=PALETTE["chip_bg"], fg=PALETTE["soft"]))

    # -------------------------------------------------------------------------
    # Chat Bubble Management (User vs Assistant Speech Bubbles)
    # -------------------------------------------------------------------------
    def add_message(self, is_user: bool, text: str, agent: str = "") -> None:
        """Appends authentic user or assistant bubble to the conversation stream."""
        bubble_row = tk.Frame(self.chat_scroll_frame, bg=PALETTE["surface"])
        bubble_row.pack(fill=tk.X, pady=4, padx=4)

        if is_user:
            # User Bubble: Aligned right, purple container
            wrapper = tk.Frame(
                bubble_row,
                bg=PALETTE["user_bg"],
                highlightbackground=PALETTE["user_br"],
                highlightthickness=1,
                padx=10,
                pady=6,
            )
            wrapper.pack(side=tk.RIGHT, anchor=tk.E)

            lbl = tk.Label(
                wrapper,
                text=text,
                font=("Segoe UI", 9),
                fg=PALETTE["text_primary"],
                bg=PALETTE["user_bg"],
                wraplength=340,
                justify=tk.LEFT,
            )
            lbl.pack()
        else:
            # Assistant Bubble: Aligned left, dark surface container with AgentTag
            wrapper = tk.Frame(
                bubble_row,
                bg=PALETTE["asst_bg"],
                highlightbackground=PALETTE["asst_br"],
                highlightthickness=1,
                padx=10,
                pady=6,
            )
            wrapper.pack(side=tk.LEFT, anchor=tk.W)

            if agent:
                tag = tk.Label(
                    wrapper,
                    text=agent.upper(),
                    font=("Segoe UI", 7, "bold"),
                    fg=PALETTE["soft"],
                    bg=PALETTE["asst_bg"],
                    anchor=tk.W,
                )
                tag.pack(anchor=tk.W, pady=(0, 2))

            lbl = tk.Label(
                wrapper,
                text=text,
                font=("Segoe UI", 9),
                fg=PALETTE["text_primary"],
                bg=PALETTE["asst_bg"],
                wraplength=340,
                justify=tk.LEFT,
            )
            lbl.pack(anchor=tk.W)

            self._last_assistant_output = text
            if self.target_hwnd:
                paste_btn = tk.Label(
                    wrapper,
                    text="⚡ Paste in App (Shift+Enter)",
                    font=("Segoe UI", 7, "bold"),
                    fg=PALETTE["accent"],
                    bg=PALETTE["surface_card"],
                    padx=6,
                    pady=2,
                    cursor="hand2",
                )
                paste_btn.pack(anchor=tk.W, pady=(4, 0))
                paste_btn.bind("<Button-1>", lambda e, t=text: self._paste_into_target_app(t))
                paste_btn.bind("<Enter>", lambda e, b=paste_btn: b.configure(bg=PALETTE["hi"], fg="#FFFFFF"))
                paste_btn.bind("<Leave>", lambda e, b=paste_btn: b.configure(bg=PALETTE["surface_card"], fg=PALETTE["accent"]))

        # Auto-scroll to bottom
        self.root.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def add_web_search_bubble(self, query: str, results: List[Dict[str, str]]) -> None:
        """Appends native search results card to the conversation stream."""
        bubble_row = tk.Frame(self.chat_scroll_frame, bg=PALETTE["surface"])
        bubble_row.pack(fill=tk.X, pady=4, padx=4)

        wrapper = tk.Frame(
            bubble_row,
            bg=PALETTE["asst_bg"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        wrapper.pack(side=tk.LEFT, anchor=tk.W, fill=tk.X, expand=True)

        header_frame = tk.Frame(wrapper, bg=PALETTE["asst_bg"])
        header_frame.pack(fill=tk.X, pady=(0, 4))

        tag = tk.Label(
            header_frame,
            text="WEB SEARCH",
            font=("Segoe UI", 7, "bold"),
            fg=PALETTE["accent"],
            bg=PALETTE["surface"],
            padx=4,
            pady=1,
        )
        tag.pack(side=tk.LEFT)

        q_lbl = tk.Label(
            header_frame,
            text=f"'{query}'",
            font=("Segoe UI", 8, "italic"),
            fg=PALETTE["text_secondary"],
            bg=PALETTE["asst_bg"],
        )
        q_lbl.pack(side=tk.LEFT, padx=6)

        if not results:
            empty_lbl = tk.Label(
                wrapper,
                text="No search results found.",
                font=("Segoe UI", 8),
                fg=PALETTE["text_muted"],
                bg=PALETTE["asst_bg"],
            )
            empty_lbl.pack(anchor=tk.W, pady=2)
        else:
            for item in results[:4]:
                title = item.get("title", "Untitled")
                url = item.get("url", "")
                snippet = item.get("snippet", "")

                card = tk.Frame(
                    wrapper,
                    bg=PALETTE["surface_card"],
                    highlightbackground=PALETTE["border"],
                    highlightthickness=1,
                    padx=8,
                    pady=4,
                )
                card.pack(fill=tk.X, pady=2)

                t_lbl = tk.Label(
                    card,
                    text=title,
                    font=("Segoe UI", 8, "bold"),
                    fg=PALETTE["soft"],
                    bg=PALETTE["surface_card"],
                    cursor="hand2",
                    anchor=tk.W,
                    justify=tk.LEFT,
                    wraplength=320,
                )
                t_lbl.pack(anchor=tk.W)
                if url:
                    t_lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
                    t_lbl.bind("<Enter>", lambda e, l=t_lbl: l.configure(fg=PALETTE["text_primary"]))
                    t_lbl.bind("<Leave>", lambda e, l=t_lbl: l.configure(fg=PALETTE["soft"]))

                if snippet:
                    s_lbl = tk.Label(
                        card,
                        text=snippet[:180] + ("..." if len(snippet) > 180 else ""),
                        font=("Segoe UI", 7),
                        fg=PALETTE["text_secondary"],
                        bg=PALETTE["surface_card"],
                        anchor=tk.W,
                        justify=tk.LEFT,
                        wraplength=320,
                    )
                    s_lbl.pack(anchor=tk.W, pady=(2, 0))

                if url:
                    u_display = url if len(url) <= 45 else url[:42] + "..."
                    u_lbl = tk.Label(
                        card,
                        text=f"↗ {u_display}",
                        font=("Segoe UI", 7),
                        fg=PALETTE["accent"],
                        bg=PALETTE["surface_card"],
                        cursor="hand2",
                        anchor=tk.W,
                    )
                    u_lbl.pack(anchor=tk.W, pady=(2, 0))
                    u_lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        self.root.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def add_web_page_bubble(self, page_data: Dict[str, Any]) -> None:
        """Appends native web page summary card to the conversation stream."""
        bubble_row = tk.Frame(self.chat_scroll_frame, bg=PALETTE["surface"])
        bubble_row.pack(fill=tk.X, pady=4, padx=4)

        wrapper = tk.Frame(
            bubble_row,
            bg=PALETTE["asst_bg"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        wrapper.pack(side=tk.LEFT, anchor=tk.W, fill=tk.X, expand=True)

        header_frame = tk.Frame(wrapper, bg=PALETTE["asst_bg"])
        header_frame.pack(fill=tk.X, pady=(0, 4))

        tag = tk.Label(
            header_frame,
            text="PAGE VIEWER",
            font=("Segoe UI", 7, "bold"),
            fg=PALETTE["green"],
            bg=PALETTE["surface"],
            padx=4,
            pady=1,
        )
        tag.pack(side=tk.LEFT)

        status_code = page_data.get("status_code", 200)
        code_lbl = tk.Label(
            header_frame,
            text=f"HTTP {status_code}",
            font=("Segoe UI", 7, "bold"),
            fg=PALETTE["green"] if status_code == 200 else PALETTE["warning"],
            bg=PALETTE["asst_bg"],
        )
        code_lbl.pack(side=tk.LEFT, padx=6)

        title = page_data.get("title") or "Web Page Document"
        url = page_data.get("url", "")
        text_content = page_data.get("text", "")

        card = tk.Frame(
            wrapper,
            bg=PALETTE["surface_card"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        card.pack(fill=tk.X, pady=2)

        t_lbl = tk.Label(
            card,
            text=title,
            font=("Segoe UI", 8, "bold"),
            fg=PALETTE["text_primary"],
            bg=PALETTE["surface_card"],
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=320,
        )
        t_lbl.pack(anchor=tk.W)

        if text_content:
            clean_excerpt = text_content.strip()[:300]
            if len(text_content.strip()) > 300:
                clean_excerpt += "..."
            c_lbl = tk.Label(
                card,
                text=clean_excerpt,
                font=("Segoe UI", 8),
                fg=PALETTE["text_secondary"],
                bg=PALETTE["surface_card"],
                anchor=tk.W,
                justify=tk.LEFT,
                wraplength=320,
            )
            c_lbl.pack(anchor=tk.W, pady=(4, 2))

        if url:
            action_btn = tk.Label(
                card,
                text="🌐 Open Full Page in Browser",
                font=("Segoe UI", 7, "bold"),
                fg=PALETTE["accent"],
                bg=PALETTE["surface_card"],
                cursor="hand2",
                anchor=tk.W,
            )
            action_btn.pack(anchor=tk.W, pady=(4, 0))
            action_btn.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        self.root.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    # -------------------------------------------------------------------------
    # Ambient Canvas Animations: Status Dot & Staggered ThinkDots
    # -------------------------------------------------------------------------
    def _start_ambient_animations(self) -> None:
        self._ambient_after_id = None
        def _tick():
            if not self._is_alive or not self.root:
                return
            try:
                if not self.root.winfo_exists():
                    return
            except Exception:
                return
            self._pulse_phase += 0.14
            self._render_status_dot()
            if self.is_running:
                self._render_thinking_dots()
            try:
                self._ambient_after_id = self.root.after(80, _tick)
            except Exception:
                pass

        try:
            self._ambient_after_id = self.root.after(100, _tick)
        except Exception:
            pass

    def _render_status_dot(self) -> None:
        """Renders connected green or voice red dot on compact bar."""
        self.status_dot_canvas.delete("all")
        color = PALETTE["red"] if self.voice_active else PALETTE["green"]
        self.status_dot_canvas.create_oval(1, 1, 8, 8, fill=color, outline="")

    def _render_thinking_dots(self) -> None:
        """Renders 3 staggered pulsating thinking dots when agent is reasoning."""
        self.thinking_dots_canvas.delete("all")
        for i, x in enumerate([6, 14, 22]):
            offset = i * 0.8
            alpha = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self._pulse_phase * 2.0 + offset))
            r = 2.0 + 1.0 * alpha
            self.thinking_dots_canvas.create_oval(
                x - r, 6 - r, x + r, 6 + r, fill=PALETTE["soft"], outline=""
            )

    # -------------------------------------------------------------------------
    # Input Focus & Placeholder Handlers
    # -------------------------------------------------------------------------
    def _on_compact_focus_in(self, event: Any) -> None:
        self.compact_input_box.configure(highlightbackground=PALETTE["hi"])
        if self._compact_has_placeholder:
            self.compact_entry_var.set("")
            self.compact_entry.configure(fg=PALETTE["text_primary"])
            self._compact_has_placeholder = False

    def _on_compact_focus_out(self, event: Any) -> None:
        self.compact_input_box.configure(highlightbackground=PALETTE["border"])
        if not self.compact_entry_var.get().strip():
            self.compact_entry_var.set("Reply to Makima...")
            self.compact_entry.configure(fg=PALETTE["text_muted"])
            self._compact_has_placeholder = True

    def _on_compact_key(self, event: Any) -> None:
        if self._compact_has_placeholder:
            self.compact_entry_var.set("")
            self.compact_entry.configure(fg=PALETTE["text_primary"])
            self._compact_has_placeholder = False

    def _on_exp_focus_in(self, event: Any) -> None:
        self.exp_input_box.configure(highlightbackground=PALETTE["hi"])
        if self._exp_has_placeholder:
            self.exp_entry_var.set("")
            self.exp_entry.configure(fg=PALETTE["text_primary"])
            self._exp_has_placeholder = False

    def _on_exp_focus_out(self, event: Any) -> None:
        self.exp_input_box.configure(highlightbackground=PALETTE["border"])
        if not self.exp_entry_var.get().strip():
            self.exp_entry_var.set("Ask Makima anything...")
            self.exp_entry.configure(fg=PALETTE["text_muted"])
            self._exp_has_placeholder = True

    def _on_exp_key(self, event: Any) -> None:
        if self._exp_has_placeholder:
            self.exp_entry_var.set("")
            self.exp_entry.configure(fg=PALETTE["text_primary"])
            self._exp_has_placeholder = False

    # -------------------------------------------------------------------------
    # Drag & Movement Handling
    # -------------------------------------------------------------------------
    def _start_drag(self, event: Any) -> None:
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event: Any) -> None:
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    # -------------------------------------------------------------------------
    # Visibility, Focus & Global Hotkey
    # -------------------------------------------------------------------------
    def show(self) -> None:
        """Shows the HUD in top-center of active desktop."""
        self.is_visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._update_context_chip_display()
        if self.is_expanded:
            self.exp_entry.focus_set()
        else:
            self.compact_entry.focus_set()

    def hide(self) -> None:
        """Hides the HUD from view."""
        self.is_visible = False
        self.root.withdraw()

    def toggle_visibility(self) -> None:
        """Toggles between visible and hidden state."""
        self.root.after(0, self._toggle_ui)

    def _toggle_ui(self) -> None:
        if self.is_visible:
            self.hide()
        else:
            self.show()

    def _on_focus_out(self, event: Any) -> None:
        pass

    def _start_global_hotkey(self) -> None:
        """Starts background pynput keyboard listener for Ctrl+Space."""
        try:
            from pynput import keyboard

            def _on_activate():
                self._capture_screen_context()
                self.toggle_visibility()

            hotkeys = keyboard.GlobalHotKeys({"<ctrl>+<space>": _on_activate})
            hotkeys.daemon = True
            hotkeys.start()
            self._hotkey_listener = hotkeys
            logger.info("Global hotkey (Ctrl+Space) registered successfully.")
        except Exception as exc:
            logger.warning("Could not register global hotkey (Ctrl+Space): %s", exc)

    # -------------------------------------------------------------------------
    # Screen-Aware Context Capture & Command-K Helpers
    # -------------------------------------------------------------------------
    def _resolve_app_name(self, proc_name: str) -> str:
        p = proc_name.lower().strip()
        app_map = {
            "code.exe": "VS Code",
            "chrome.exe": "Chrome",
            "msedge.exe": "Edge",
            "firefox.exe": "Firefox",
            "notepad.exe": "Notepad",
            "windowsterminal.exe": "Terminal",
            "cmd.exe": "Command Prompt",
            "powershell.exe": "PowerShell",
            "explorer.exe": "Explorer",
            "slack.exe": "Slack",
            "discord.exe": "Discord",
            "sublime_text.exe": "Sublime Text",
            "pycharm64.exe": "PyCharm",
            "devenv.exe": "Visual Studio",
            "winword.exe": "Word",
            "excel.exe": "Excel",
        }
        if p in app_map:
            return app_map[p]
        cleaned = re.sub(r"\.exe$", "", p, flags=re.IGNORECASE)
        return cleaned.capitalize() if cleaned else "App"

    def _capture_screen_context(self) -> None:
        """Captures active foreground window and highlighted selection text."""
        if not win32gui:
            return
        try:
            fg_hwnd = win32gui.GetForegroundWindow()
            if not fg_hwnd or not win32gui.IsWindow(fg_hwnd):
                return

            try:
                my_hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                if fg_hwnd == my_hwnd:
                    return
            except Exception:
                pass

            self.target_hwnd = fg_hwnd
            self.target_title = win32gui.GetWindowText(fg_hwnd).strip()

            proc_name = "unknown"
            if win32process and psutil:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                    if pid > 0:
                        proc_name = psutil.Process(pid).name()
                except Exception:
                    pass
            self.target_app_name = self._resolve_app_name(proc_name)

            self._capture_selection_from_foreground()
            self._safe_dispatch(self._update_context_chip_display)
        except Exception as exc:
            logger.debug("Screen context capture notice: %s", exc)

    def _capture_selection_from_foreground(self) -> None:
        """Simulates Ctrl+C on active window to peek highlighted selection with clipboard preservation."""
        prev_clip = None
        try:
            prev_clip = self.root.clipboard_get()
        except Exception:
            prev_clip = ""

        sentinel = f"__makima_peek_{time.time()}__"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(sentinel)
            self.root.update()
        except Exception:
            pass

        try:
            VK_CONTROL = 0x11
            VK_C = 0x43
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
            time.sleep(0.015)
            ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.025)
        except Exception:
            pass

        new_clip = None
        try:
            new_clip = self.root.clipboard_get()
        except Exception:
            new_clip = ""

        if new_clip and new_clip != sentinel and new_clip.strip():
            self.captured_selection = new_clip.strip()
        else:
            self.captured_selection = ""
            if prev_clip:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(prev_clip)
                    self.root.update()
                except Exception:
                    pass

    def _update_context_chip_display(self) -> None:
        """Renders or hides the context chip based on current captured state."""
        if self.captured_selection or self.target_app_name:
            preview = (self.captured_selection or "").replace("\n", " ").strip()
            if len(preview) > 34:
                preview = preview[:31] + "..."
            label_text = f"📄 {self.target_app_name or 'Active App'}"
            if preview:
                label_text += f' · "{preview}"'
            self.context_chip_lbl.configure(text=label_text)
            self.context_chip_frame.pack(
                fill=tk.X,
                pady=(0, 6),
                before=self.compact_bar if not self.is_expanded else self.exp_header,
            )
            if not self.is_expanded:
                self.root.geometry(f"{self.width}x82+{self.pos_x}+{self.pos_y}")
        else:
            self.context_chip_frame.pack_forget()
            if not self.is_expanded:
                self.root.geometry(f"{self.width}x{self.compact_height}+{self.pos_x}+{self.pos_y}")

    def clear_context(self) -> None:
        """Clears captured context and hides chip."""
        self.captured_selection = ""
        self.target_hwnd = None
        self.target_title = ""
        self.target_app_name = ""
        self._update_context_chip_display()

    def _extract_code_or_text(self, text: str) -> str:
        """Extracts primary code block if present; otherwise returns clean text."""
        clean = text.strip()
        code_match = re.search(r"```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```", clean, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        return clean

    def _paste_into_target_app(self, text: Optional[str] = None) -> bool:
        """Restores target application focus and pastes content in-place (Command-K)."""
        content = text or self._last_assistant_output
        if not content:
            return False

        to_paste = self._extract_code_or_text(content)

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(to_paste)
            self.root.update()
        except Exception as exc:
            logger.debug("Clipboard set notice: %s", exc)

        self.hide()

        if self.target_hwnd and win32gui and win32gui.IsWindow(self.target_hwnd):
            try:
                if win32con and win32gui.IsIconic(self.target_hwnd):
                    win32gui.ShowWindow(self.target_hwnd, win32con.SW_RESTORE)
                win32gui.BringWindowToTop(self.target_hwnd)
                if win32con:
                    win32gui.ShowWindow(self.target_hwnd, win32con.SW_SHOW)
                try:
                    win32gui.SetForegroundWindow(self.target_hwnd)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Focus restore notice: %s", exc)

            time.sleep(0.04)

            try:
                VK_CONTROL = 0x11
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002
                ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
                time.sleep(0.015)
                ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return True
            except Exception as exc:
                logger.debug("Paste simulation notice: %s", exc)
        return False

    def _on_shift_return_compact(self) -> None:
        query = self.compact_entry_var.get().strip()
        if not query or self._compact_has_placeholder:
            self._paste_into_target_app()
            return
        self._auto_paste_on_finish = True
        self._on_compact_submit()

    def _on_shift_return_exp(self) -> None:
        query = self.exp_entry_var.get().strip()
        if not query or self._exp_has_placeholder:
            self._paste_into_target_app()
            return
        self._auto_paste_on_finish = True
        self._on_exp_submit()

    # -------------------------------------------------------------------------
    # Dynamic Geometry: Expand / Collapse (Old Makima Style)
    # -------------------------------------------------------------------------
    def expand(self) -> None:
        """Expands the HUD downwards to show full chat history and tools."""
        if not self.is_expanded:
            self.is_expanded = True
            self.compact_bar.pack_forget()
            self.expanded_frame.pack(fill=tk.BOTH, expand=True)
            self._update_context_chip_display()
            self.root.geometry(f"{self.width}x{self.expanded_height}+{self.pos_x}+{self.pos_y}")
            self.exp_entry.focus_set()

    def collapse(self) -> None:
        """Collapses the HUD back to compact pill."""
        if self.is_expanded:
            self.is_expanded = False
            self.expanded_frame.pack_forget()
            self.compact_bar.pack(fill=tk.X)
            self._update_context_chip_display()
            target_h = 82 if (self.captured_selection or self.target_app_name) else self.compact_height
            self.root.geometry(f"{self.width}x{target_h}+{self.pos_x}+{self.pos_y}")
            self.compact_entry.focus_set()

    def _toggle_pin(self) -> None:
        self.is_pinned = not self.is_pinned
        self.root.attributes("-topmost", self.is_pinned)
        self.pin_btn.configure(fg=PALETTE["soft"] if self.is_pinned else PALETTE["text_muted"])

    # -------------------------------------------------------------------------
    # Step DAG & Output Viewport (Compatibility with Test Suite)
    # -------------------------------------------------------------------------
    def clear_steps(self) -> None:
        for widget in self.dag_steps_frame.winfo_children():
            widget.destroy()

    def add_step(self, icon: str, text: str, status: str = "running") -> None:
        color = PALETTE["accent"] if status == "running" else PALETTE["success"]
        row = tk.Frame(self.dag_steps_frame, bg=PALETTE["surface_card"])
        row.pack(fill=tk.X, pady=1)

        icon_lbl = tk.Label(
            row, text=icon, font=("Segoe UI", 8), fg=color, bg=PALETTE["surface_card"], width=3
        )
        icon_lbl.pack(side=tk.LEFT)

        msg_lbl = tk.Label(
            row,
            text=text,
            font=("Segoe UI", 8),
            fg=PALETTE["text_primary"] if status == "running" else PALETTE["text_secondary"],
            bg=PALETTE["surface_card"],
            anchor=tk.W,
        )
        msg_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def set_output(self, text: str) -> None:
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, text)

    # -------------------------------------------------------------------------
    # User Action Approvals / Denials (Security Bar)
    # -------------------------------------------------------------------------
    def show_confirmation(self, message: str) -> None:
        self.confirmation_lbl.configure(text=f"! {message}")
        self.confirmation_frame.pack(fill=tk.X, pady=(0, 6), before=self.exp_input_box)

    def hide_confirmation(self) -> None:
        self.confirmation_frame.pack_forget()

    def _approve_action(self) -> None:
        self.hide_confirmation()
        self.add_message(is_user=False, text="Action approved by user.", agent="Security")

    def _reject_action(self) -> None:
        self.hide_confirmation()
        self.add_message(is_user=False, text="Action blocked by user.", agent="Security")

    def _toggle_voice(self) -> None:
        self.voice_active = not self.voice_active
        if self.voice_active:
            self.voice_btn.configure(text="⏹️ Stop Voice", bg="#321818", fg="#FCA5A5")
            self.status_strip.configure(text="Voice listening active (Gemini Live)...")
            threading.Thread(target=self._start_gemini_voice, daemon=True).start()
        else:
            self.voice_btn.configure(text="🎙️ Voice", bg=PALETTE["surface_card"], fg=PALETTE["text_secondary"])
            self.status_strip.configure(text="Connected to Makima Core")
            threading.Thread(target=self._stop_gemini_voice, daemon=True).start()

    def _start_gemini_voice(self) -> None:
        """Connects to Gemini Live audio controller without any local TTS models."""
        try:
            if self._voice_controller is None:
                from makima.voice.controller import LiveVoiceController
                def _on_hud_status(event_type: str, payload: Any = None) -> None:
                    try:
                        if event_type == "turn_complete":
                            self.root.after(0, lambda: self.status_strip.configure(text="Jarvis: Listening for follow-up..."))
                        elif event_type == "interrupted":
                            self.root.after(0, lambda: self.status_strip.configure(text="Jarvis: Listening to user..."))
                    except Exception:
                        pass
                self._voice_controller = LiveVoiceController(on_status=_on_hud_status)
            asyncio.run(self._voice_controller.start())
        except Exception as exc:
            logger.debug("Gemini voice start notice: %s", exc)

    def _stop_gemini_voice(self) -> None:
        """Stops Gemini Live voice controller."""
        try:
            if self._voice_controller is not None:
                asyncio.run(self._voice_controller.stop())
        except Exception as exc:
            logger.debug("Gemini voice stop notice: %s", exc)

    def _open_chat(self) -> None:
        self.add_message(is_user=False, text="Makima Web Workspace accessible at http://127.0.0.1:8000", agent="Core")

    # -------------------------------------------------------------------------
    # Asynchronous Agent Query Dispatch
    # -------------------------------------------------------------------------
    def _on_compact_submit(self) -> None:
        query = self.compact_entry_var.get().strip()
        if not query or self._compact_has_placeholder or self.is_running:
            return
        self.expand()
        self._submit_prompt(query)

    def _on_exp_submit(self) -> None:
        query = self.exp_entry_var.get().strip()
        if not query or self._exp_has_placeholder or self.is_running:
            return
        self._submit_prompt(query)

    def _submit_prompt(self, query: str) -> None:
        self._exp_has_placeholder = False
        self.exp_entry_var.set("")
        self.compact_entry_var.set("")

        # Screen-Aware Context Enrichment
        if self.captured_selection:
            app_info = self.target_app_name or "Active Window"
            if self.target_title:
                app_info += f" ({self.target_title})"
            enriched_prompt = (
                f"Context from {app_info}:\n"
                f"```\n{self.captured_selection}\n```\n\n"
                f"User Request: {query}"
            )
            display_text = f"{query}\n[Context: {self.target_app_name or 'Active Window'}]"
        else:
            enriched_prompt = query
            display_text = query

        self.add_message(is_user=True, text=display_text)
        self.clear_steps()
        self.set_output("Processing query with autonomous agent...")
        self.is_running = True
        self.status_strip.configure(text="Thinking...")
        self.thinking_frame.pack(fill=tk.X, pady=(0, 4), before=self.exp_input_box)
        self.add_step("✦", f"Goal: {query}", status="running")

        threading.Thread(target=self._agent_worker, args=(enriched_prompt,), daemon=True).start()

    def _safe_dispatch(self, callback: Callable[[], None]) -> None:
        """Pushes a UI update callback into the thread-safe queue."""
        self._dispatch_queue.put(callback)

    def _process_dispatch_queue(self) -> None:
        """Executes queued callbacks on the main Tkinter thread."""
        if not self._is_alive or not self.root:
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        while not self._dispatch_queue.empty():
            try:
                cb = self._dispatch_queue.get_nowait()
                cb()
            except Exception as exc:
                logger.debug("Dispatch error: %s", exc)
        if self._is_alive and self.root:
            try:
                self._dispatch_after_id = self.root.after(30, self._process_dispatch_queue)
            except Exception:
                pass

    def destroy(self) -> None:
        """Cleanly destroys the HUD root window and cancels background timers."""
        self._is_alive = False
        if hasattr(self, "_ambient_after_id") and self._ambient_after_id and self.root:
            try:
                self.root.after_cancel(self._ambient_after_id)
            except Exception:
                pass
        if hasattr(self, "_dispatch_after_id") and self._dispatch_after_id and self.root:
            try:
                self.root.after_cancel(self._dispatch_after_id)
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _agent_worker(self, query: str) -> None:
        t0 = time.perf_counter()
        try:
            clean_q = query.strip()

            # 1. Fast-Path A: Direct URL entry -> fetch_web_page
            if URL_RE.match(clean_q):
                url = clean_q
                if not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                self._safe_dispatch(lambda: self.add_step("🌐", f"Fetching: {url}", "running"))
                page_data = asyncio.run(fetch_web_page(url))
                duration = round(time.perf_counter() - t0, 2)

                def _on_page_done():
                    self.clear_steps()
                    if page_data.get("success"):
                        self.add_step("✔️", f"Fetched in {duration}s: {page_data.get('title', url)[:28]}", "done")
                        self.set_output(page_data.get("text", "")[:400])
                        self.add_web_page_bubble(page_data)
                    else:
                        err = page_data.get("error", "Failed to fetch page")
                        self.add_step("⚠️", f"Error: {err}", "warning")
                        self.add_message(is_user=False, text=f"Could not load {url}: {err}", agent="Browser")
                    self.thinking_frame.pack_forget()
                    self.status_strip.configure(text="Ready")
                    self.is_running = False

                self._safe_dispatch(_on_page_done)
                return

            # 2. Fast-Path B: Search queries ("search for ...", "browse ...", "find online ...")
            search_match = SEARCH_RE.match(clean_q)
            if search_match:
                term = search_match.group(1).strip()
                self._safe_dispatch(lambda: self.add_step("🔍", f"Searching: {term}", "running"))
                search_data = asyncio.run(search_web(term, max_results=4))
                duration = round(time.perf_counter() - t0, 2)

                def _on_search_done():
                    self.clear_steps()
                    results = search_data.get("results", [])
                    if search_data.get("success") and results:
                        self.add_step("✔️", f"Search completed in {duration}s ({len(results)} results)", "done")
                        self.set_output(f"Found {len(results)} results for '{term}'.")
                        self.add_web_search_bubble(term, results)
                    else:
                        err = search_data.get("error") or "No results found."
                        self.add_step("⚠️", f"Notice: {err}", "warning")
                        self.add_message(is_user=False, text=f"Search for '{term}': {err}", agent="Browser")
                    self.thinking_frame.pack_forget()
                    self.status_strip.configure(text="Ready")
                    self.is_running = False

                self._safe_dispatch(_on_search_done)
                return

            # 3. Agent Execution Engine
            if self.engine is None:
                from makima.runtime import build_engine
                self.engine = build_engine(registry=self.registry)

            self._safe_dispatch(lambda: self.add_step("⚙️", "Planning execution & tools...", "running"))

            sig = inspect.signature(self.engine.run)
            run_kwargs: Dict[str, Any] = {"prompt": query}
            if "task" in sig.parameters:
                run_kwargs["task"] = "fast_chat"
            if "messages" in sig.parameters:
                run_kwargs["messages"] = None
            elif "history" in sig.parameters:
                run_kwargs["history"] = self.conversation_history
            if "tools" in sig.parameters:
                run_kwargs["tools"] = self.registry

            async def _run():
                return await self.engine.run(**run_kwargs)

            res = asyncio.run(_run())

            duration = round(time.perf_counter() - t0, 2)
            content = getattr(res, "content", None) or "Completed without output."
            tool_count = getattr(res, "tool_calls_executed", 0)

            def _on_done():
                self.clear_steps()
                self.add_step("✔️", f"Goal completed in {duration}s ({tool_count} tools used)", "done")
                self.set_output(content)
                self.add_message(is_user=False, text=content, agent="Yukino")
                self.thinking_frame.pack_forget()
                self.status_strip.configure(text="Ready")
                self.is_running = False
                if getattr(self, "_auto_paste_on_finish", False):
                    self._auto_paste_on_finish = False
                    self._paste_into_target_app(content)

            self._safe_dispatch(_on_done)

        except Exception as exc:
            logger.exception("Agent dispatch failed: %s", exc)
            err_str = str(exc)

            def _on_err():
                self.add_step("⚠️", f"Error: {err_str}", "warning")
                self.set_output(f"Operation failed:\n{err_str}")
                self.add_message(is_user=False, text=f"Operation failed:\n{err_str}", agent="System")
                self.thinking_frame.pack_forget()
                self.status_strip.configure(text="Error occurred")
                self.is_running = False

            self._safe_dispatch(_on_err)

    def mainloop(self) -> None:
        """Enters the Tkinter main event loop."""
        try:
            self.root.mainloop()
        finally:
            self._is_alive = False


def launch_overlay(engine: Optional[HermesAgentEngine] = None) -> SpotlightHUD:
    """Convenience launcher for the Makima Spotlight HUD."""
    hud = SpotlightHUD(engine=engine)
    return hud


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    hud = launch_overlay()
    hud.mainloop()
