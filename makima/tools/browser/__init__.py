"""
Makima v2 — Web Browser & Page Automation Package.
Architectural Pattern: Library-first Web Navigation, Extraction, and Headless Browser Automation.
Zero-Hardcoding Guarantee: Fully dynamic HTTP client with BeautifulSoup sanitation and Playwright automation.
"""

from __future__ import annotations

from makima.tools.browser.automation import (
    BrowserController,
    browse_page,
    browser_interact,
    get_browser_controller,
)
from makima.tools.browser.fetcher import fetch_web_page, search_web

__all__ = [
    "fetch_web_page",
    "search_web",
    "browse_page",
    "browser_interact",
    "BrowserController",
    "get_browser_controller",
]
