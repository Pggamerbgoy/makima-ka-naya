"""
Makima v2 — Desktop Overlay & Spotlight HUD Subsystem.
Architectural Pattern: Native Windows top-most floating Spotlight HUD with DWM glass effects,
global hotkey activation (Ctrl+Space), real-time step DAG tracker, and Hermes engine integration.
"""

from makima.overlay.hud import SpotlightHUD, launch_overlay

__all__ = ["SpotlightHUD", "launch_overlay"]
