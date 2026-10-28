"""Headless Chromium (system package) driven by Playwright, for JavaScript-heavy pages.

One page at a time and the browser is closed after every job: the Pi 4 only has 2 GB of RAM.
"""

from __future__ import annotations

import asyncio
import logging

from mib.worker.http import USER_AGENT

log = logging.getLogger(__name__)

_BLOCKED = frozenset({"image", "media", "font"})


class Renderer:
    def __init__(self, executable: str | None) -> None:
        self.executable = executable
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        try:
            import playwright.async_api  # noqa: F401

            self._importable = True
        except ImportError:
            self._importable = False

    @property
    def available(self) -> bool:
        return bool(self.executable) and self._importable

    async def _ensure(self):
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                executable_path=self.executable,
                headless=True,
                args=["--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--mute-audio"],
            )
        return self._browser

    async def render(self, url: str, timeout_s: float = 25.0) -> tuple[int | None, str, str]:
        """Returns (status, html, final_url)."""
        if not self.available:
            raise RuntimeError("headless Chromium is not available on this worker")
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        async with self._lock:
            browser = await self._ensure()
            context = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
            try:
                async def _route(route):
                    if route.request.resource_type in _BLOCKED:
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", _route)
                page = await context.new_page()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=6000)
                except PlaywrightTimeout:
                    pass
                return (response.status if response else None), await page.content(), page.url
            finally:
                await context.close()

    async def close(self) -> None:
        browser, pw = self._browser, self._pw
        self._browser = self._pw = None
        try:
            if browser is not None:
                await browser.close()
        except Exception:  # browser may already be gone
            log.debug("browser close failed", exc_info=True)
        if pw is not None:
            await pw.stop()
