"""Browser automation helper for third-party signal sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from playwright.async_api import Browser, BrowserContext, async_playwright

logger = logging.getLogger(__name__)


class BrowserAutomation:
    """Lightweight Playwright wrapper for signal sources."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    async def get_context(self) -> BrowserContext:
        """Get or create a shared browser context."""
        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless
                )
            if self._context is None:
                self._context = await self._browser.new_context()
            return self._context

    async def close(self) -> None:
        """Close browser resources."""
        async with self._lock:
            if self._context:
                await self._context.close()
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
