"""
Makima v2 — Spotlight HUD Overlay CLI Launcher.
Run with: python -m makima.overlay.main

Features:
1. Native GPU Hardware-Accelerated Slint Overlay (makima-native-overlay.exe)
   - Real Skia/FemtoVG GPU acceleration, true transparent glass, 0% blur
2. High-DPI Pure Python Windows Native HUD (SpotlightHUD)
   - Per-monitor DPI awareness, Win32 DWM acrylic blur, DwmExtendFrame drop shadows
"""

from __future__ import annotations

import logging
import pathlib
import subprocess
import sys

from makima.overlay.hud import SpotlightHUD


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 70)
    print("👑 MAKIMA v2 — SPOTLIGHT HUD OVERLAY INITIALIZED")
    print("• Press [Ctrl + Space] anywhere on Windows to toggle the HUD.")
    print("• Press [Esc] to dismiss or hide the HUD.")
    print("• Click and drag the top title area to reposition.")
    print("=" * 70)

    # Check for compiled Rust Slint overlay binary
    bin_path = pathlib.Path(__file__).parent / "bin" / "makima-native-overlay.exe"
    exe_target = bin_path if bin_path.exists() else None

    # Default to Slint GPU native binary if available, fallback to High-DPI Python HUD
    if "--python" not in sys.argv and exe_target is not None:
        print(f"🚀 Launching Hardware-Accelerated Slint GPU Overlay: {exe_target}")
        proc = subprocess.Popen([str(exe_target)])
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return 0

    print("🚀 Launching High-DPI Windows Native HUD...")
    hud = SpotlightHUD()
    hud.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
