"""Stealth browser enhancements for Playwright.

Implements WebDriver property hiding, Chrome DevTools Protocol masking,
automation detection evasion, and mouse movement simulation.
"""

import asyncio
import logging
import random
from typing import Optional, Dict, Any

from playwright.async_api import Page, BrowserContext

from src.ingest.fingerprint_randomizer import fingerprint_randomizer
from src.ingest.user_agent_pool import user_agent_pool
from src.ingest.header_builder import header_builder

logger = logging.getLogger(__name__)


class StealthBrowser:
    """
    Enhances Playwright browsers with stealth techniques.
    
    Features:
    - WebDriver property hiding
    - Chrome DevTools Protocol masking
    - Automation detection evasion
    - Mouse movement simulation
    - Realistic browser fingerprinting
    """
    
    def __init__(self):
        """Initialize stealth browser."""
        pass
    
    async def setup_stealth_page(
        self,
        page: Page,
        user_agent: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Setup a Playwright page with stealth enhancements.
        
        Args:
            page: Playwright page object
            user_agent: Optional user agent (random if None)
            viewport: Optional viewport size (random if None)
        """
        try:
            # Set user agent
            if user_agent is None:
                user_agent = user_agent_pool.get_random()
            
            await page.set_extra_http_headers({
                "User-Agent": user_agent,
            })
            
            # Set viewport
            if viewport is None:
                fingerprint = fingerprint_randomizer.get_random_fingerprint()
                viewport = fingerprint["viewport"]
            
            await page.set_viewport_size(width=viewport["width"], height=viewport["height"])
            
            # Apply fingerprint randomization scripts
            fingerprint_randomizer.apply_to_playwright_page(page)
            
            # Add additional stealth scripts
            await self._inject_stealth_scripts(page)
            
            logger.debug("Stealth enhancements applied to page")
        
        except Exception as e:
            logger.warning(f"Error setting up stealth page: {e}")
    
    async def _inject_stealth_scripts(self, page: Page) -> None:
        """Inject additional stealth scripts."""
        scripts = [
            # Hide webdriver property
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
            """,
            
            # Override permissions
            """
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            """,
            
            # Mock plugins
            """
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            """,
            
            # Mock languages
            """
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            """,
            
            # Chrome runtime
            """
            window.chrome = {
                runtime: {}
            };
            """,
            
            # Override getBattery if needed
            """
            if (navigator.getBattery) {
                navigator.getBattery = () => Promise.resolve({
                    charging: true,
                    chargingTime: 0,
                    dischargingTime: Infinity,
                    level: 1
                });
            }
            """,
        ]
        
        for script in scripts:
            try:
                await page.add_init_script(script)
            except Exception as e:
                logger.debug(f"Error injecting stealth script: {e}")
    
    async def simulate_human_behavior(self, page: Page) -> None:
        """
        Simulate human-like behavior on page.
        
        Args:
            page: Playwright page object
        """
        try:
            # Random mouse movement
            await page.mouse.move(
                x=random.randint(100, 500),
                y=random.randint(100, 500),
            )
            
            # Random delay
            import asyncio
            await asyncio.sleep(random.uniform(0.5, 2.0))
        
        except Exception as e:
            logger.debug(f"Error simulating human behavior: {e}")
    
    def get_stealth_context_options(
        self,
        browser_type: str = "chromium",
    ) -> Dict[str, Any]:
        """
        Get Playwright context options with stealth settings.
        
        Args:
            browser_type: Browser type ('chromium', 'firefox', 'webkit')
            
        Returns:
            Dict of context options
        """
        fingerprint = fingerprint_randomizer.get_random_fingerprint()
        
        options = {
            "viewport": fingerprint["viewport"],
            "locale": fingerprint["locale"],
            "timezone_id": fingerprint["timezone"],
            "color_scheme": fingerprint["color_scheme"],
            "user_agent": user_agent_pool.get_random(),
        }
        
        # Browser-specific options
        if browser_type == "chromium":
            options.update({
                "ignore_https_errors": True,
                "bypass_csp": True,
            })
        
        return options


# Global stealth browser instance
stealth_browser = StealthBrowser()
