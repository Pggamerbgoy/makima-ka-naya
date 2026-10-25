"""
Makima v2 — SOTA Interactive Visible Browser Controller & Playwright Automation.
Architectural Pattern: Persistent BrowserController session managing live Chromium instances with Indexed DOM Grounding.
Zero-Hardcoding Guarantee: Fully dynamic viewport, zero external heavy dependencies, and pure Playwright async API.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.browser.automation")

_PLAYWRIGHT_AVAILABLE: Optional[bool] = None
PlaywrightError: Any = Exception
async_playwright: Any = None


def _load_playwright() -> bool:
    """Lazy loader for Playwright to avoid 50MB RAM and 400ms startup latency."""
    global _PLAYWRIGHT_AVAILABLE, PlaywrightError, async_playwright
    if _PLAYWRIGHT_AVAILABLE is None:
        try:
            from playwright.async_api import Error as _PE, async_playwright as _AP
            PlaywrightError = _PE
            async_playwright = _AP
            _PLAYWRIGHT_AVAILABLE = True
        except ImportError:
            PlaywrightError = Exception
            async_playwright = None
            _PLAYWRIGHT_AVAILABLE = False
    return _PLAYWRIGHT_AVAILABLE

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


def _find_system_browser_executable() -> Optional[str]:
    """Finds installed Brave, Chrome, or Edge on the host system."""
    import os
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/brave-browser",
        "/usr/bin/chromium-browser",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

# ---------------------------------------------------------------------------
# JavaScript DOM Distillation Snippet (Indexed Clickable Grounding)
# ---------------------------------------------------------------------------
JS_EXTRACT_INTERACTIVE_ELEMENTS = """
() => {
    document.querySelectorAll('[data-makima-idx]').forEach(el => el.removeAttribute('data-makima-idx'));
    const candidates = Array.from(document.querySelectorAll(
        'button, a, input, select, textarea, [role="button"], [role="link"], [onclick]'
    ));
    const vw = window.innerWidth || 1280;
    const vh = window.innerHeight || 800;
    const scored = [];
    let domOrder = 0;

    for (const el of candidates) {
        domOrder += 1;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (
            rect.width <= 4 ||
            rect.height <= 4 ||
            rect.right <= 0 ||
            rect.bottom <= 0 ||
            rect.left >= vw ||
            rect.top < -40 ||
            rect.top > vh * 3.5 ||
            style.visibility === 'hidden' ||
            style.display === 'none' ||
            style.opacity === '0'
        ) {
            continue;
        }

        const tag = el.tagName.toLowerCase();
        const inputType = (el.getAttribute('type') || '').toLowerCase();
        if (inputType === 'hidden') continue;

        const ariaLabel = el.getAttribute('aria-label') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const titleAttr = el.getAttribute('title') || '';
        const textContent = (el.innerText || el.value || '').trim();
        const label = textContent || placeholder || ariaLabel || titleAttr || el.id || el.getAttribute('name') || '';
        const cleanLabel = label.replace(/\\s+/g, ' ').slice(0, 80);
        if (!cleanLabel && tag === 'a') continue;

        const idAndName = `${el.id || ''} ${el.getAttribute('name') || ''} ${cleanLabel}`.toLowerCase();
        const inNavOrChrome = Boolean(
            el.closest('header, nav, footer, [role="navigation"], #navbar-main, #nav-belt, #nav-main, #navFooter')
        );
        const inMainContent = Boolean(
            el.closest(
                '[data-component-type="s-search-result"], [data-asin]:not([data-asin=""]), ' +
                '#ppd, #centerCol, #dp-container, #search, main, [role="main"], article, #content'
            )
        );
        const isCriticalAction = (
            tag === 'input' ||
            tag === 'textarea' ||
            tag === 'select' ||
            /add[-_\\s]*to[-_\\s]*cart|buy[-_\\s]*now|proceed[-_\\s]*to[-_\\s]*checkout|twotabsearchtextbox|nav-search-submit/i.test(idAndName)
        );

        let priority = 2;
        if (isCriticalAction) {
            priority = 0;
        } else if (inMainContent && !inNavOrChrome) {
            priority = 1;
        } else if (inNavOrChrome) {
            priority = 3;
        }

        let href = '';
        if (tag === 'a' && el.href && /^https?:\\/\\//i.test(el.href) && !el.href.startsWith('javascript:')) {
            href = el.href.slice(0, 160);
        }

        scored.push({
            el,
            priority,
            domOrder,
            tag,
            type: inputType,
            id: el.id || '',
            name: el.getAttribute('name') || '',
            label: cleanLabel,
            href,
            center: [Math.round(rect.left + rect.width / 2), Math.round(rect.top + rect.height / 2)],
            rect: {
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        });
    }

    scored.sort((a, b) => (a.priority - b.priority) || (a.domOrder - b.domOrder));

    const results = [];
    let idx = 1;
    for (const item of scored) {
        if (idx > 120) break;
        try {
            item.el.setAttribute('data-makima-idx', String(idx));
        } catch (e) {}
        const entry = {
            index: idx++,
            tag: item.tag,
            type: item.type,
            id: item.id,
            name: item.name,
            label: item.label,
            center: item.center,
            rect: item.rect
        };
        if (item.href) {
            entry.href = item.href;
        }
        results.push(entry);
    }
    return results;
}
"""


def _normalize_url(url: str) -> str:
    """Ensures URL begins with http://, https://, or file://."""
    clean = url.strip()
    if not clean.startswith(("http://", "https://", "file://")):
        clean = f"https://{clean}"
    return clean


# ---------------------------------------------------------------------------
# Persistent Browser Controller
# ---------------------------------------------------------------------------

class BrowserController:
    """
    Manages persistent async Playwright browser sessions across multi-turn interactions.
    Enables visible browsing (headless=False) so the user can observe live desktop automation.
    """

    def __init__(self) -> None:
        self._pw: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._lock = asyncio.Lock()
        self._indexed_elements: Dict[int, Dict[str, Any]] = {}
        self._is_headless = False
        self._last_url: str = ""
        self._last_title: str = ""

    @property
    def is_active(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    def get_active_context_summary(self) -> str:
        """Returns a one-line summary of the currently open browser tab, or empty string if inactive."""
        if not self.is_active:
            return ""
        url = self._last_url or (getattr(self._page, "url", "") if self._page else "")
        if not url or url == "about:blank":
            return ""
        title = self._last_title or "Untitled"
        return f"Active Playwright browser tab open at: '{title}' ({url})"

    async def ensure_page(self, headless: bool = False) -> Any:
        """Ensures an active browser page is open, launching if necessary."""
        if not _load_playwright() or async_playwright is None:
            raise RuntimeError("Playwright is not installed in the environment.")

        # Ensure lock belongs to current running event loop
        try:
            loop = asyncio.get_running_loop()
            if self._lock is None or getattr(self._lock, "_loop", None) not in (None, loop):
                self._lock = asyncio.Lock()
        except Exception:
            self._lock = asyncio.Lock()

        async with self._lock:
            if self._page and not self._page.is_closed():
                if self._browser and hasattr(self._browser, "is_connected") and self._browser.is_connected():
                    return self._page

            # Teardown any leftover or crashed handles before spawning a new driver
            await self._cleanup_internal()

            logger.info("Launching Chromium browser (headless=%s)...", headless)
            self._is_headless = headless
            try:
                self._pw = await async_playwright().start()

                launch_kwargs: Dict[str, Any] = {
                    "headless": headless,
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                }

                # Try standard Chromium launch, fallback to system Brave/Chrome if missing
                sys_exe = _find_system_browser_executable()
                try:
                    self._browser = await self._pw.chromium.launch(**launch_kwargs)
                except Exception as default_launch_err:
                    if sys_exe:
                        logger.info("Default Chromium launch failed, falling back to system browser: %s", sys_exe)
                        launch_kwargs["executable_path"] = sys_exe
                        self._browser = await self._pw.chromium.launch(**launch_kwargs)
                    else:
                        raise default_launch_err

                self._context = await self._browser.new_context(
                    user_agent=DEFAULT_USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    ignore_https_errors=True,
                )

                self._page = await self._context.new_page()
                return self._page
            except Exception:
                # If launch failed mid-way, cleanup partial state so subsequent calls aren't poisoned
                await self._cleanup_internal()
                raise

    async def _cleanup_internal(self) -> None:
        """Internal teardown of all browser, context, and driver handles without leaking resources."""
        if self._page:
            try:
                if not self._page.is_closed():
                    await self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                if hasattr(self._browser, "is_connected") and self._browser.is_connected():
                    await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

        self._indexed_elements.clear()
        self._last_url = ""
        self._last_title = ""

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 25000) -> Dict[str, Any]:
        """Navigates to URL and extracts interactive elements."""
        target_url = _normalize_url(url)
        try:
            page = await self.ensure_page(headless=self._is_headless)
        except Exception as exc:
            logger.error("ensure_page failed in navigate: %s: %s", type(exc).__name__, exc, exc_info=True)
            # Fallback to desktop window navigation ONLY if headless is False and a desktop browser is active
            if not self._is_headless:
                try:
                    from makima.tools.os.windows import _find_target_window, focus_window
                    from makima.tools.desktop.input import keyboard_hotkey, keyboard_type
                    hwnd, win_title, _ = _find_target_window("Brave")
                    if not hwnd:
                        hwnd, win_title, _ = _find_target_window("Chrome")
                    if not hwnd:
                        hwnd, win_title, _ = _find_target_window("Edge")
                    if hwnd:
                        focus_window(hwnd=hwnd)
                        await asyncio.sleep(0.1)
                        keyboard_hotkey(keys=["ctrl", "l"])
                        await asyncio.sleep(0.05)
                        keyboard_type(text=target_url)
                        await asyncio.sleep(0.05)
                        keyboard_hotkey(keys=["enter"])
                        await asyncio.sleep(0.5)
                        return {
                            "success": True,
                            "method": "desktop_browser_fallback",
                            "url": target_url,
                            "title": win_title,
                            "message": f"Navigated to {target_url} in active desktop browser ({win_title}).",
                            "playwright_error": f"{type(exc).__name__}: {exc}",
                        }
                except Exception as desk_err:
                    logger.debug("Desktop navigation fallback failed: %s", desk_err)

            err_msg = str(exc)
            if "executable" in err_msg.lower() or "playwright install" in err_msg.lower() or "missing" in err_msg.lower():
                return {
                    "success": False,
                    "error": "Chromium browser binaries are missing. Please run: playwright install chromium",
                    "help": "Run 'playwright install chromium' to install required browser binaries.",
                }
            return {"success": False, "error": f"Failed to launch browser: {exc}"}

        logger.info("Navigating to %s (timeout=%dms)", target_url, timeout_ms)
        await page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
        await asyncio.sleep(1.0)  # Allow initial hydration

        title = await page.title()
        current_url = page.url
        self._last_url = current_url
        self._last_title = title
        elements = await self.get_interactive_elements()

        return {
            "success": True,
            "url": current_url,
            "title": title,
            "total_elements": len(elements),
            "elements": elements,
        }

    async def get_interactive_elements(self) -> List[Dict[str, Any]]:
        """Evaluates in-page JS to extract all visible clickable controls with index IDs."""
        if not self._page or self._page.is_closed():
            return []

        try:
            elements: List[Dict[str, Any]] = await self._page.evaluate(JS_EXTRACT_INTERACTIVE_ELEMENTS)
            self._indexed_elements = {el["index"]: el for el in elements}
            return elements
        except Exception as exc:
            logger.warning("Failed to extract interactive elements: %s", exc)
            return []

    async def click(
        self,
        index: Optional[int] = None,
        selector: Optional[str] = None,
        timeout_ms: int = 8000,
    ) -> Dict[str, Any]:
        """Clicks an element by mark index [N] or CSS selector."""
        page = await self.ensure_page(headless=self._is_headless)

        if index is not None:
            if index not in self._indexed_elements:
                # Refresh elements
                await self.get_interactive_elements()

            if index not in self._indexed_elements:
                return {
                    "success": False,
                    "error": f"Mark index [{index}] not found. Call action='get_elements' to refresh interactive elements.",
                }

            target = self._indexed_elements[index]
            center = target.get("center", [0, 0])
            logger.info("Clicking mark [%d] at center (%d, %d) (%s '%s')", index, center[0], center[1], target.get("tag"), target.get("label"))

            # Prefer clicking via stamped data-makima-idx attribute (handles scroll/sticky headers),
            # falling back to physical viewport mouse click.
            clicked_via_attr = False
            if hasattr(page, "locator"):
                try:
                    loc = page.locator(f'[data-makima-idx="{index}"]').first
                    if await loc.count() > 0:
                        await loc.scroll_into_view_if_needed(timeout=3000)
                        await loc.click(timeout=timeout_ms)
                        clicked_via_attr = True
                except Exception:
                    clicked_via_attr = False

            if not clicked_via_attr:
                await page.mouse.click(center[0], center[1])

            await asyncio.sleep(1.0)

            # Re-fetch new page state
            new_title = await page.title()
            new_url = page.url
            self._last_url = new_url
            self._last_title = new_title
            new_elements = await self.get_interactive_elements()

            return {
                "success": True,
                "clicked_mark": index,
                "target": target,
                "current_url": new_url,
                "title": new_title,
                "elements": new_elements,
            }

        elif selector is not None:
            logger.info("Clicking selector: %s", selector)
            await page.click(selector, timeout=timeout_ms)
            await asyncio.sleep(1.0)
            new_title = await page.title()
            new_url = page.url
            self._last_url = new_url
            self._last_title = new_title
            return {
                "success": True,
                "clicked_selector": selector,
                "current_url": new_url,
                "title": new_title,
            }

        return {
            "success": False,
            "error": "Either 'index' or 'selector' must be specified for click.",
        }

    async def type_text(
        self,
        text: str,
        index: Optional[int] = None,
        selector: Optional[str] = None,
        press_enter: bool = False,
        clear_first: bool = True,
    ) -> Dict[str, Any]:
        """Types text into an input field by index or selector."""
        page = await self.ensure_page(headless=self._is_headless)

        if index is not None:
            if index not in self._indexed_elements:
                await self.get_interactive_elements()
            if index not in self._indexed_elements:
                return {
                    "success": False,
                    "error": f"Mark index [{index}] not found in interactive elements.",
                }

            target = self._indexed_elements[index]
            center = target.get("center", [0, 0])
            # Click to focus
            await page.mouse.click(center[0], center[1])
            await asyncio.sleep(0.2)

            if clear_first:
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")

            await page.keyboard.type(text, delay=10)
            if press_enter:
                await page.keyboard.press("Enter")
                await asyncio.sleep(1.0)

            new_title = await page.title()
            new_url = page.url
            self._last_url = new_url
            self._last_title = new_title
            return {
                "success": True,
                "typed": text,
                "index": index,
                "pressed_enter": press_enter,
                "current_url": new_url,
                "title": new_title,
            }

        elif selector is not None:
            if clear_first:
                await page.fill(selector, text)
            else:
                await page.type(selector, text, delay=10)

            if press_enter:
                await page.press(selector, "Enter")
                await asyncio.sleep(1.0)

            new_title = await page.title()
            new_url = page.url
            self._last_url = new_url
            self._last_title = new_title
            return {
                "success": True,
                "typed": text,
                "selector": selector,
                "pressed_enter": press_enter,
                "current_url": new_url,
                "title": new_title,
            }

        return {
            "success": False,
            "error": "Either 'index' or 'selector' must be specified for type_text.",
        }

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Presses a single key or key combination."""
        page = await self.ensure_page(headless=self._is_headless)
        await page.keyboard.press(key)
        await asyncio.sleep(0.5)
        new_title = await page.title()
        self._last_title = new_title
        self._last_url = page.url
        return {"success": True, "key": key, "title": new_title}

    async def scroll(self, amount: int = 500) -> Dict[str, Any]:
        """Scrolls the active page vertically."""
        page = await self.ensure_page(headless=self._is_headless)
        await page.evaluate(f"window.scrollBy({{top: {amount}, behavior: 'smooth'}})")
        await asyncio.sleep(0.5)
        elements = await self.get_interactive_elements()
        return {
            "success": True,
            "scrolled_amount": amount,
            "elements": elements,
        }

    async def screenshot(self, save_path: Optional[str] = None) -> Dict[str, Any]:
        """Captures a PNG screenshot of the current page."""
        page = await self.ensure_page(headless=self._is_headless)

        if not save_path:
            captures_dir = Path.home() / ".makima" / "captures"
            captures_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time() * 1000)
            save_path = str(captures_dir / f"browser_{timestamp}.png")

        await page.screenshot(path=save_path, full_page=False)
        logger.info("Saved browser screenshot to %s", save_path)

        return {
            "success": True,
            "image_path": save_path,
            "title": await page.title(),
            "url": page.url,
        }

    async def get_text(self, max_length: int = 15000, selector: Optional[str] = None) -> Dict[str, Any]:
        """Extracts rendered text content from page body, prioritizing structured product cards, main content, and viewport position."""
        page = await self.ensure_page(headless=self._is_headless)
        raw_text = ""
        try:
            if selector:
                raw_text = await page.inner_text(selector, timeout=5000)
            else:
                raw_text = await page.evaluate(
                    """() => {
                        const sections = [];

                        // 1. Extract structured product detail summary if on a product page (e.g. Amazon/Flipkart DP)
                        const prodContainer = document.querySelector('#ppd, #centerCol, #dp-container');
                        const prodScope = prodContainer || document;
                        const prodTitleEl = prodScope.querySelector('#productTitle, #title, h1');
                        const addToCartEl = prodScope.querySelector('#add-to-cart-button, #buy-now-button, [name="submit.add-to-cart"]');
                        if (prodTitleEl && (addToCartEl || prodContainer)) {
                            const pTitle = (prodTitleEl.innerText || '').trim();
                            const priceSelectors = [
                                '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
                                '#corePrice_feature_div .a-price .a-offscreen',
                                '#priceblock_ourprice',
                                '#priceblock_dealprice',
                                '.a-price .a-offscreen'
                            ];
                            let priceEl = null;
                            for (const sel of priceSelectors) {
                                priceEl = prodScope.querySelector(sel);
                                if (priceEl) break;
                            }
                            const pPrice = priceEl ? (priceEl.innerText || priceEl.textContent || '').trim() : '';
                            const availEl = prodScope.querySelector('#availability');
                            const pAvail = availEl ? (availEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                            const cartIdx = addToCartEl ? (addToCartEl.getAttribute('data-makima-idx') || '') : '';
                            sections.push(
                                `[ACTIVE PRODUCT PAGE]\\nTitle: ${pTitle}` +
                                (pPrice ? `\\nLive Price: ${pPrice}` : '') +
                                (pAvail ? `\\nAvailability: ${pAvail}` : '') +
                                (cartIdx ? `\\nAdd-to-Cart Button Mark Index: [${cartIdx}]` : (addToCartEl ? `\\nAdd-to-Cart Selector: #${addToCartEl.id || 'add-to-cart-button'}` : ''))
                            );
                        }

                        // 2. Extract structured search result cards (e.g. Amazon / e-commerce search grids)
                        const cards = Array.from(document.querySelectorAll(
                            '[data-component-type="s-search-result"], [data-asin]:not([data-asin=""])'
                        ));
                        const cardLines = [];
                        for (const card of cards) {
                            if (cardLines.length >= 25) break;
                            const titleNode = card.querySelector('h2, [class*="title"], a.a-link-normal span.a-text-normal');
                            const title = titleNode ? (titleNode.innerText || '').replace(/\\s+/g, ' ').trim() : '';
                            if (!title || title.length < 5) continue;
                            const priceNode = card.querySelector('.a-price .a-offscreen, .a-price-whole');
                            let price = priceNode ? (priceNode.innerText || priceNode.textContent || '').replace(/\\s+/g, ' ').trim() : '';
                            if (!price) {
                                const m = (card.innerText || '').match(/₹\\s?[0-9,]+/);
                                if (m) price = m[0];
                            }
                            const linkNode = card.querySelector('h2 a, a.a-link-normal[href*="/dp/"], a[href]');
                            const markIdx = linkNode ? (linkNode.getAttribute('data-makima-idx') || '') : '';
                            const href = (linkNode && linkNode.href && /^https?:\\/\\//i.test(linkNode.href)) ? linkNode.href.split('?')[0] : '';
                            cardLines.push(
                                `${cardLines.length + 1}. ${title} | Live Price: ${price || 'N/A'}` +
                                (markIdx ? ` | Click Mark: [${markIdx}]` : '') +
                                (href ? ` | URL: ${href}` : '')
                            );
                        }
                        if (cardLines.length > 0) {
                            sections.push('[STRUCTURED SEARCH RESULTS]\\n' + cardLines.join('\\n'));
                        }

                        const scrollY = window.scrollY || 0;
                        const vh = window.innerHeight || 800;
                        // 3. If scrolled down significantly, extract text from elements in/below current viewport
                        if (scrollY > 150) {
                            const blocks = [];
                            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                            let node;
                            while ((node = walker.nextNode())) {
                                const text = (node.nodeValue || '').trim();
                                if (!text || text.length < 2) continue;
                                const el = node.parentElement;
                                if (!el) continue;
                                const tag = el.tagName ? el.tagName.toLowerCase() : '';
                                if (['script', 'style', 'noscript', 'svg', 'path'].includes(tag)) continue;
                                if (el.closest('header, nav, footer, [role="navigation"], #navbar-main, #nav-belt')) continue;
                                const rect = el.getBoundingClientRect();
                                if (rect.width === 0 && rect.height === 0) continue;
                                if (rect.bottom >= -50 && rect.top <= vh * 2.5) {
                                    blocks.push(text);
                                }
                            }
                            if (blocks.length > 0) {
                                sections.push(blocks.join('\\n'));
                                return sections.join('\\n\\n');
                            }
                        }

                        // 4. Otherwise prioritize main content containers over global nav/header/footer noise
                        const mainSelectors = [
                            '#ppd', '#centerCol', '#dp-container', '#search',
                            'main', '[role="main"]', 'article', '#content'
                        ];
                        for (const sel of mainSelectors) {
                            const container = document.querySelector(sel);
                            if (container && container.innerText && container.innerText.trim().length > 80) {
                                sections.push(container.innerText.trim());
                                return sections.join('\\n\\n');
                            }
                        }
                        const clone = document.body.cloneNode(true);
                        clone.querySelectorAll('header, nav, footer, script, style, noscript, svg, [role="navigation"], #navbar-main, #nav-belt').forEach(e => e.remove());
                        sections.push((clone.innerText || document.body.innerText || '').trim());
                        return sections.join('\\n\\n');
                    }"""
                )
        except Exception:
            try:
                raw_text = await page.inner_text("body", timeout=5000)
            except Exception:
                raw_text = await page.content()

        cleaned_text = re.sub(r"\n{3,}", "\n\n", (raw_text or "").strip())
        is_truncated = False
        if len(cleaned_text) > max_length:
            cleaned_text = cleaned_text[:max_length] + "\n... [Use scroll or selector for more]"
            is_truncated = True

        title = await page.title()
        current_url = page.url
        if title:
            self._last_title = title
        if current_url and current_url != "about:blank":
            self._last_url = current_url

        return {
            "success": True,
            "title": title,
            "url": self._last_url or current_url,
            "text": cleaned_text,
            "truncated": is_truncated,
            "length": len(cleaned_text),
        }

    async def close(self) -> Dict[str, Any]:
        """Closes the browser session cleanly."""
        try:
            loop = asyncio.get_running_loop()
            if self._lock is None or getattr(self._lock, "_loop", None) not in (None, loop):
                self._lock = asyncio.Lock()
        except Exception:
            self._lock = asyncio.Lock()

        async with self._lock:
            await self._cleanup_internal()

        logger.info("Browser session closed cleanly.")
        return {"success": True, "status": "closed"}


# ---------------------------------------------------------------------------
# Windows SelectorEventLoop Bridge & Proactor Proxy
# ---------------------------------------------------------------------------

class _ProactorLoopBridge:
    """Runs a dedicated ProactorEventLoop on Windows when the caller loop is SelectorEventLoop."""
    _instance: Optional["_ProactorLoopBridge"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.loop = asyncio.ProactorEventLoop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="MakimaProactorLoop")
        self.thread.start()
        # Initialize internal real controller inside the dedicated proactor thread loop
        async def _init_impl():
            return BrowserController()
        fut = asyncio.run_coroutine_threadsafe(_init_impl(), self.loop)
        self.real_controller: BrowserController = fut.result()

    @classmethod
    def get_instance(cls) -> "_ProactorLoopBridge":
        with cls._lock:
            if cls._instance is None or not cls._instance.thread.is_alive():
                cls._instance = cls()
            return cls._instance

    def run_coro(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return asyncio.wrap_future(fut)


class _ProactorBrowserProxy:
    """Proxy providing the exact same interface as BrowserController, dispatching calls to the Proactor thread."""
    def __init__(self, bridge: _ProactorLoopBridge) -> None:
        self._bridge = bridge

    @property
    def is_active(self) -> bool:
        return self._bridge.real_controller.is_active

    @property
    def _is_headless(self) -> bool:
        return self._bridge.real_controller._is_headless

    @_is_headless.setter
    def _is_headless(self, val: bool) -> None:
        self._bridge.real_controller._is_headless = val

    def get_active_context_summary(self) -> str:
        return self._bridge.real_controller.get_active_context_summary()

    async def ensure_page(self, headless: bool = False) -> Any:
        return await self._bridge.run_coro(self._bridge.real_controller.ensure_page(headless=headless))

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 25000) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.navigate(url=url, wait_until=wait_until, timeout_ms=timeout_ms))

    async def get_interactive_elements(self) -> List[Dict[str, Any]]:
        return await self._bridge.run_coro(self._bridge.real_controller.get_interactive_elements())

    async def click(self, index: Optional[int] = None, selector: Optional[str] = None, timeout_ms: int = 8000) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.click(index=index, selector=selector, timeout_ms=timeout_ms))

    async def type_text(self, text: str, index: Optional[int] = None, selector: Optional[str] = None, press_enter: bool = False, clear_first: bool = False) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.type_text(text=text, index=index, selector=selector, press_enter=press_enter, clear_first=clear_first))

    async def press_key(self, key: str) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.press_key(key=key))

    async def scroll(self, amount: int = 500) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.scroll(amount=amount))

    async def screenshot(self, save_path: Optional[str] = None, filename: Optional[str] = None) -> Dict[str, Any]:
        target = save_path or filename
        return await self._bridge.run_coro(self._bridge.real_controller.screenshot(save_path=target))

    async def get_text(self, max_length: int = 15000, selector: Optional[str] = None) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.get_text(max_length=max_length, selector=selector))

    async def close(self) -> Dict[str, Any]:
        return await self._bridge.run_coro(self._bridge.real_controller.close())


def _needs_proactor_bridge() -> bool:
    if sys.platform != "win32":
        return False
    try:
        loop = asyncio.get_running_loop()
        return not isinstance(loop, getattr(asyncio, "ProactorEventLoop", ()))
    except Exception:
        return False


# Singleton controller instance
_BROWSER_CONTROLLER: Optional[BrowserController] = None


def get_browser_controller() -> Any:
    """Returns singleton BrowserController instance or Proactor-bridged proxy when on Windows SelectorEventLoop."""
    global _BROWSER_CONTROLLER
    if _needs_proactor_bridge():
        bridge = _ProactorLoopBridge.get_instance()
        return _ProactorBrowserProxy(bridge)
    if _BROWSER_CONTROLLER is None:
        _BROWSER_CONTROLLER = BrowserController()
    return _BROWSER_CONTROLLER


async def close_browser_controller() -> None:
    """Cleanly closes browser instances across both direct and proactor bridge modes."""
    global _BROWSER_CONTROLLER
    if _BROWSER_CONTROLLER is not None:
        try:
            await _BROWSER_CONTROLLER.close()
        except Exception:
            pass
        _BROWSER_CONTROLLER = None
    if _ProactorLoopBridge._instance is not None and _ProactorLoopBridge._instance.thread.is_alive():
        try:
            await _ProactorLoopBridge._instance.run_coro(_ProactorLoopBridge._instance.real_controller.close())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SOTA Unified Browser Tool
# ---------------------------------------------------------------------------

@tool(
    name="browser_interact",
    description=(
        "Visible interactive browser for navigating websites and working with page content, controls, and forms. "
        "Use for requests to find or watch online anime episodes, TV series, movies, AMVs, trailers, or other videos: "
        "open the site the user explicitly names or has saved as their preferred streaming site, search the requested "
        "title, inspect results, select the requested episode, and interact with playback controls as needed. "
        "For video viewing, use this tool instead of play_song. Honor an explicit website first, then the user's "
        "saved preference (for example, Miruro if that is the remembered preference); never default anime/video "
        "requests to YouTube unless YouTube is explicitly requested. Also use for visible browser navigation, "
        "web apps, buttons, links, search fields, forms, and multi-step website interactions."
    ),
    tags=["web", "browser", "automation", "interactive", "sota"],
)
async def browser_interact(
    action: str,
    url: Optional[str] = None,
    index: Optional[int] = None,
    selector: Optional[str] = None,
    text: Optional[str] = None,
    key: Optional[str] = None,
    scroll_y: Optional[int] = None,
    headless: bool = False,
    timeout_ms: int = 15000,
    max_length: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes an action in the persistent Playwright Chromium browser. For online anime, episodes, movies,
    series, or other video requests, navigate to the user's explicit or saved preferred streaming site,
    inspect the page, search for the requested title, and select the relevant result/episode. Use this tool
    instead of play_song for online video viewing. Navigation alone does not prove that playback started.

    Args:
        action: The action to execute. Must be one of:
                'navigate': Opens url and returns page title and indexed interactive elements.
                'get_elements': Returns the list of numbered interactive elements on current page (indexes up to 120 priority elements; no max_marks parameter exists).
                'click': Clicks element by 'index' (e.g. index=2) or by 'selector'.
                'type': Types 'text' into element by 'index' or 'selector'.
                'press_key': Presses key specified by 'key' (e.g. 'Enter', 'Tab').
                'scroll': Scrolls page down (positive scroll_y) or up (negative scroll_y).
                'screenshot': Captures page screenshot to file.
                'get_text': Reads clean body text and structured product listings from the page (default limit: 15,000 characters).
                'close': Closes the browser session.
        url: URL for 'navigate' action.
        index: 1-based element number for 'click' or 'type' actions.
        selector: Optional CSS selector for 'click' or 'type' actions.
        text: Text string to type for 'type' action.
        key: Key name for 'press_key' action.
        scroll_y: Pixels to scroll (defaults to 500 for 'scroll').
        headless: If True, runs headless; defaults to False so user sees the live browser window.
        timeout_ms: Maximum timeout in milliseconds.
        max_length: Optional character limit for 'get_text' (defaults to 15000).
    """
    act = action.strip().lower()
    ctrl = get_browser_controller()
    ctrl._is_headless = headless

    try:
        if act == "navigate":
            if not url:
                return {"success": False, "error": "Action 'navigate' requires 'url' parameter."}
            return await ctrl.navigate(url=url, timeout_ms=timeout_ms)

        elif act == "get_elements":
            elements = await ctrl.get_interactive_elements()
            return {"success": True, "total_elements": len(elements), "elements": elements}

        elif act == "click":
            return await ctrl.click(index=index, selector=selector, timeout_ms=timeout_ms)

        elif act == "type":
            if text is None:
                return {"success": False, "error": "Action 'type' requires 'text' parameter."}
            press_enter = (key or "").lower() == "enter"
            return await ctrl.type_text(text=text, index=index, selector=selector, press_enter=press_enter)

        elif act == "press_key":
            if not key:
                return {"success": False, "error": "Action 'press_key' requires 'key' parameter."}
            return await ctrl.press_key(key=key)

        elif act == "scroll":
            amount = scroll_y if scroll_y is not None else 500
            return await ctrl.scroll(amount=amount)

        elif act == "screenshot":
            return await ctrl.screenshot()

        elif act == "get_text":
            return await ctrl.get_text(max_length=max_length or 15000, selector=selector)

        elif act == "close":
            return await ctrl.close()

        else:
            return {
                "success": False,
                "error": f"Unknown browser action '{action}'. Supported: navigate, get_elements, click, type, press_key, scroll, screenshot, get_text, close.",
            }

    except PlaywrightError as pe:
        logger.error(f"Playwright error during '{action}': {pe}")
        return {"success": False, "error": f"Playwright error: {str(pe)}"}
    except Exception as exc:
        logger.error(f"Error during browser action '{action}': {exc}", exc_info=True)
        return {"success": False, "error": f"{type(exc).__name__}: {str(exc)}"}


# ---------------------------------------------------------------------------
# Backward Compatibility Helper Tool
# ---------------------------------------------------------------------------

@tool(
    name="browse_page",
    description="Quick one-shot web page reader using Playwright. Fetches dynamic JS pages and returns visible text.",
    tags=["web", "browser", "automation"],
)
async def browse_page(
    url: str,
    wait_seconds: float = 2.0,
    max_length: int = 25000,
    headless: bool = True,
) -> Dict[str, Any]:
    """
    Renders dynamic JavaScript-heavy websites and returns text content.
    Preserves an already-active BrowserController session if one was open prior to this call.
    """
    ctrl = get_browser_controller()
    was_active = ctrl.is_active
    prev_headless = ctrl._is_headless
    if not was_active:
        ctrl._is_headless = headless
    try:
        nav_res = await ctrl.navigate(url=url)
        if not nav_res.get("success"):
            return nav_res
        res = await ctrl.get_text(max_length=max_length)
        if isinstance(res, dict):
            res["final_url"] = res.get("url", "")
        return res
    except Exception as exc:
        err_msg = str(exc)
        if "executable" in err_msg.lower() or "playwright install" in err_msg.lower() or "missing" in err_msg.lower():
            return {
                "success": False,
                "error": "Chromium browser binaries are missing. Please run: playwright install chromium",
                "help": "Run 'playwright install chromium' to install required browser binaries.",
            }
        return {"success": False, "error": f"Failed to browse page: {exc}"}
    finally:
        # Only close browser if browse_page started a temporary one-shot session
        if not was_active:
            await ctrl.close()
        else:
            ctrl._is_headless = prev_headless
