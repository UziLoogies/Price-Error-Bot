"""Headless browser fetcher for JavaScript-rendered content."""

import asyncio
import logging
import random
import re
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Tuple, Union
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright, TimeoutError as PlaywrightTimeoutError

from src.config import settings
from src.ingest.base import BaseFetcher, RawPriceData
from src.ingest.rate_limiter import rate_limiter
from src.ingest.session_manager import session_manager
from src.ingest.proxy_manager import proxy_rotator, ProxyInfo
from src.ingest.stealth_browser import stealth_browser
from src.ingest.user_agent_pool import user_agent_pool
from src.ingest.fingerprint_randomizer import fingerprint_randomizer

logger = logging.getLogger(__name__)


# Custom exception types for better error handling
class SelectorNotFoundError(Exception):
    """All selectors failed to find the target element."""
    def __init__(self, selectors: List[str], url: str, page_title: str = None):
        self.selectors = selectors
        self.url = url
        self.page_title = page_title
        super().__init__(
            f"None of {len(selectors)} selectors found on {url}"
            f"{f' (page: {page_title})' if page_title else ''}"
        )


class PageLoadError(Exception):
    """Page failed to load properly."""
    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"Failed to load {url}: {reason}")


class ProductUnavailableError(Exception):
    """Product page indicates item is unavailable."""
    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"Product unavailable at {url}: {reason}")


# Realistic user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Unavailable product indicators
UNAVAILABLE_INDICATORS = [
    "currently unavailable",
    "out of stock",
    "this item is no longer available",
    "page not found",
    "we couldn't find that page",
    "looking for something?",
    "this product is discontinued",
]

# CAPTCHA indicators
CAPTCHA_INDICATORS = [
    "enter the characters",
    "prove you're not a robot",
    "captcha",
    "verify you are a human",
    "robot check",
]


class HeadlessBrowserFetcher(BaseFetcher):
    """Fetcher using headless browser for JS-rendered prices with proxy support."""

    # Per-selector timeout in milliseconds (default: 5 seconds)
    DEFAULT_PER_SELECTOR_TIMEOUT = 5000
    
    # Timeout modes
    TIMEOUT_FAST = 3000  # Fast mode: 3s per selector
    TIMEOUT_NORMAL = 5000  # Normal mode: 5s per selector
    TIMEOUT_PATIENT = 8000  # Patient mode: 8s per selector

    def __init__(
        self,
        store_name: str,
        base_url: str,
        price_selector: Union[str, List[str]],
        title_selector: str | None = None,
        original_price_selector: Union[str, List[str], None] = None,
        wait_timeout: int = 30000,
        use_proxy: bool = True,
        per_selector_timeout: int = None,
    ):
        """
        Initialize headless browser fetcher.

        Args:
            store_name: Store identifier
            base_url: Base URL for product pages
            price_selector: CSS selector(s) for price element - can be string or list
            title_selector: Optional CSS selector for product title
            original_price_selector: Optional CSS selector(s) for strikethrough/was price
            wait_timeout: Total milliseconds budget for all selector attempts
            use_proxy: Whether to use rotating proxies
            per_selector_timeout: Milliseconds to wait per selector (default: 5000)
        """
        self.store_name = store_name
        self.base_url = base_url
        self.title_selector = title_selector
        self.wait_timeout = wait_timeout
        self.use_proxy = use_proxy
        self.per_selector_timeout = per_selector_timeout or self.DEFAULT_PER_SELECTOR_TIMEOUT
        
        # Parse selectors into lists
        self.price_selectors = self._parse_selectors(price_selector)
        self.original_price_selectors = self._parse_selectors(original_price_selector) if original_price_selector else []
        
        # Keep legacy attribute for compatibility
        self.price_selector = price_selector if isinstance(price_selector, str) else ", ".join(self.price_selectors)
        self.original_price_selector = original_price_selector

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._contexts: dict[int, BrowserContext] = {}  # proxy_id -> context
        self._default_context: Optional[BrowserContext] = None
        self._init_lock = asyncio.Lock()

    @staticmethod
    def _parse_selectors(selector_input: Union[str, List[str], None]) -> List[str]:
        """
        Parse selector input into a list of individual selectors.
        
        Args:
            selector_input: Single selector, comma-separated selectors, or list
            
        Returns:
            List of individual selectors
        """
        if selector_input is None:
            return []
        
        if isinstance(selector_input, list):
            return [s.strip() for s in selector_input if s.strip()]
        
        # Parse comma-separated string
        selectors = []
        for s in selector_input.split(","):
            s = s.strip()
            if s:
                selectors.append(s)
        
        return selectors

    async def _ensure_browser(self, proxy: Optional[ProxyInfo] = None) -> BrowserContext:
        """
        Ensure browser and context are initialized.
        
        Args:
            proxy: Optional proxy to use for this context
        """
        async with self._init_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()

            # Stealth browser launch args
            stealth_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-extensions",
            ]

            # Get user agent from pool
            user_agent = user_agent_pool.get_random()
            
            # Get fingerprint for context
            fingerprint = fingerprint_randomizer.get_random_fingerprint()

            # If using proxy, create/reuse context with proxy
            if proxy:
                if proxy.id not in self._contexts:
                    logger.info(f"Creating browser context with proxy {proxy.host}:{proxy.port}")
                    
                    if self._browser is None:
                        self._browser = await self._playwright.chromium.launch(
                            headless=True,
                            args=stealth_args,
                        )
                    
                    # Use stealth context options
                    context_options = stealth_browser.get_stealth_context_options("chromium")
                    context_options["proxy"] = proxy.playwright_config
                    context_options["user_agent"] = user_agent
                    
                    self._contexts[proxy.id] = await self._browser.new_context(**context_options)
                
                return self._contexts[proxy.id]
            
            # Default context without proxy
            if self._default_context is None:
                # Get persistent context path for session reuse
                profile_path = session_manager.get_playwright_profile_path(
                    self.store_name
                )

                if self._browser is None:
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=stealth_args,
                    )

                # Use persistent context if available
                if profile_path and profile_path.exists():
                    context_options = stealth_browser.get_stealth_context_options("chromium")
                    context_options["user_agent"] = user_agent
                    
                    self._default_context = await self._playwright.chromium.launch_persistent_context(
                        str(profile_path),
                        headless=True,
                        args=stealth_args,
                        **context_options,
                    )
                else:
                    context_options = stealth_browser.get_stealth_context_options("chromium")
                    context_options["user_agent"] = user_agent
                    
                    self._default_context = await self._browser.new_context(**context_options)

            return self._default_context

    async def close(self):
        """Close browser and cleanup."""
        # Close proxy contexts
        for proxy_id, context in self._contexts.items():
            try:
                await context.close()
            except Exception as e:
                logger.error(f"Error closing proxy context {proxy_id}: {e}")
        self._contexts.clear()

        if self._default_context:
            await self._default_context.close()
            self._default_context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _try_selectors(
        self,
        page: Page,
        selectors: List[str],
        timeout_per_selector: int = None,
    ) -> Tuple[Optional[str], Optional[any]]:
        """
        Try multiple selectors and return the first one that matches.
        
        Args:
            page: Playwright page object
            selectors: List of CSS selectors to try
            timeout_per_selector: Timeout per selector in ms
            
        Returns:
            Tuple of (successful_selector, element) or (None, None)
        """
        timeout = timeout_per_selector or self.per_selector_timeout
        
        for i, selector in enumerate(selectors):
            try:
                # First try to find immediately (element might already exist)
                element = await page.query_selector(selector)
                if element:
                    logger.debug(f"Selector {i+1}/{len(selectors)} matched immediately: {selector[:50]}...")
                    return selector, element
                
                # Wait for selector with timeout
                await page.wait_for_selector(selector, timeout=timeout)
                element = await page.query_selector(selector)
                if element:
                    logger.debug(f"Selector {i+1}/{len(selectors)} matched after wait: {selector[:50]}...")
                    return selector, element
                    
            except PlaywrightTimeoutError:
                logger.debug(f"Selector {i+1}/{len(selectors)} timed out: {selector[:50]}...")
                continue
            except Exception as e:
                logger.debug(f"Selector {i+1}/{len(selectors)} error: {selector[:50]}... - {e}")
                continue
        
        return None, None

    async def _check_page_state(self, page: Page, url: str) -> None:
        """
        Check if page loaded properly and detect error states.
        
        Args:
            page: Playwright page object
            url: URL that was loaded
            
        Raises:
            ProductUnavailableError: If product is unavailable
            PageLoadError: If page didn't load properly
        """
        try:
            # Get page title and content for analysis
            title = await page.title()
            
            # Get visible text for checking indicators
            body_text = await page.evaluate("() => document.body.innerText.toLowerCase().substring(0, 5000)")
            
            # Check for CAPTCHA (warning only, might still work)
            for indicator in CAPTCHA_INDICATORS:
                if indicator in body_text:
                    logger.warning(f"CAPTCHA detected on {url} - may need manual intervention")
                    break
            
            # Check for unavailable product
            for indicator in UNAVAILABLE_INDICATORS:
                if indicator in body_text:
                    raise ProductUnavailableError(url, f"Detected: '{indicator}'")
            
            # Check for empty page
            if len(body_text.strip()) < 100:
                raise PageLoadError(url, "Page appears empty or failed to render")
            
        except ProductUnavailableError:
            raise
        except PageLoadError:
            raise
        except Exception as e:
            logger.debug(f"Page state check error (non-fatal): {e}")

    async def _extract_price_fallback(self, page: Page) -> Optional[Decimal]:
        """
        Fallback price extraction using regex on page content.
        
        Args:
            page: Playwright page object
            
        Returns:
            Extracted price or None
        """
        try:
            # Get visible text content
            text = await page.evaluate("() => document.body.innerText")
            
            # Look for price patterns
            patterns = [
                r'\$(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)',  # $XX.XX or $X,XXX.XX
                r'Price:\s*\$?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)',
                r'(\d{1,4}(?:,\d{3})*(?:\.\d{2}))\s*(?:USD|dollars)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, text)
                if matches:
                    # Return first reasonable price found
                    for match in matches:
                        try:
                            price = Decimal(match.replace(",", ""))
                            if Decimal("0.01") <= price <= Decimal("50000"):
                                logger.info(f"Fallback regex extracted price: ${price}")
                                return price
                        except:
                            continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Fallback price extraction failed: {e}")
            return None

    async def fetch(self, identifier: str) -> RawPriceData:
        """
        Fetch price using headless browser with retry logic and proxy rotation.

        Args:
            identifier: Product SKU/ID

        Returns:
            RawPriceData with price information
        """
        max_retries = 3
        last_error = None
        current_proxy: Optional[ProxyInfo] = None

        for attempt in range(max_retries):
            try:
                # Get a proxy for this attempt if enabled
                if self.use_proxy and proxy_rotator.has_proxies():
                    current_proxy = await proxy_rotator.get_next_proxy()
                    if current_proxy:
                        logger.debug(
                            f"Using proxy {current_proxy.host}:{current_proxy.port} "
                            f"for {self.store_name} {identifier}"
                        )
                
                result = await self._do_fetch(identifier, current_proxy)
                
                # Report success to proxy rotator
                if current_proxy:
                    await proxy_rotator.report_success(current_proxy.id)
                
                return result
                
            except ProductUnavailableError as e:
                # Don't retry for unavailable products
                logger.warning(f"Product unavailable: {self.store_name} {identifier} - {e}")
                raise
                
            except SelectorNotFoundError as e:
                # Don't retry if all selectors failed (likely page layout issue)
                logger.warning(f"All selectors failed: {self.store_name} {identifier} - {e}")
                raise
                
            except Exception as e:
                last_error = e
                
                # Report failure to proxy rotator
                if current_proxy:
                    await proxy_rotator.report_failure(current_proxy.id)
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5 + random.uniform(0, 3)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {self.store_name} {identifier} "
                        f"after {wait_time:.1f}s: {type(e).__name__}: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"All {max_retries} retries failed for {self.store_name} {identifier}: {e}"
                    )

        raise last_error

    async def _do_fetch(
        self, 
        identifier: str, 
        proxy: Optional[ProxyInfo] = None
    ) -> RawPriceData:
        """
        Internal fetch implementation with multi-selector support.

        Args:
            identifier: Product SKU/ID
            proxy: Optional proxy to use

        Returns:
            RawPriceData with price information
        """
        context = await self._ensure_browser(proxy)
        url = self._build_url(identifier)
        domain = urlparse(url).netloc

        # Rate limit with retailer-specific intervals
        rate_config = settings.retailer_rate_limits.get(self.store_name, {})
        min_interval = rate_config.get("min_interval", 30)
        max_interval = rate_config.get("max_interval", 60)
        jitter = rate_config.get("jitter", 10)

        await rate_limiter.acquire_with_interval(
            domain, min_interval, max_interval, jitter
        )

        page: Optional[Page] = None
        try:
            page = await context.new_page()
            
            # Apply stealth enhancements to page
            await stealth_browser.setup_stealth_page(page)

            # Navigate to page
            logger.debug(f"Navigating to {url}")
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",  # Faster than networkidle
                    timeout=settings.headless_browser_timeout * 1000
                )
            except PlaywrightTimeoutError:
                raise PageLoadError(url, "Navigation timeout")
            except Exception as e:
                raise PageLoadError(url, str(e))

            # Wait for page to stabilize
            await asyncio.sleep(random.uniform(1, 2))

            # Check page state for errors
            await self._check_page_state(page, url)

            # Try scrolling to trigger lazy loading
            await page.evaluate("window.scrollTo(0, 300)")
            await asyncio.sleep(0.5)

            # Try all price selectors
            logger.debug(f"Trying {len(self.price_selectors)} price selectors for {identifier}")
            matched_selector, price_elem = await self._try_selectors(
                page, 
                self.price_selectors,
                self.per_selector_timeout
            )

            # If no selector matched, try fallback extraction
            current_price = None
            if not price_elem:
                logger.debug(f"No price selector matched, trying fallback extraction")
                current_price = await self._extract_price_fallback(page)
                
                if not current_price:
                    page_title = await page.title()
                    raise SelectorNotFoundError(
                        self.price_selectors, 
                        url, 
                        page_title
                    )
            else:
                price_text = await price_elem.inner_text()
                current_price = self._parse_price(price_text)
                logger.info(
                    f"Price found for {identifier}: ${current_price} "
                    f"(selector: {matched_selector[:40]}...)"
                )

            # Extract original/strikethrough price if selectors provided
            original_price = None
            if self.original_price_selectors:
                _, orig_elem = await self._try_selectors(
                    page, 
                    self.original_price_selectors,
                    3000  # Shorter timeout for optional field
                )
                if orig_elem:
                    try:
                        orig_text = await orig_elem.inner_text()
                        original_price = self._parse_price(orig_text)
                    except Exception:
                        pass  # Original price is optional

            # Extract title if selector provided
            title = None
            if self.title_selector:
                try:
                    title_elem = await page.query_selector(self.title_selector)
                    if title_elem:
                        title = await title_elem.inner_text()
                        title = title.strip() if title else None
                except Exception:
                    pass  # Title is optional

            return RawPriceData(
                sku=identifier,
                url=url,
                store=self.store_name,
                current_price=current_price,
                msrp=original_price,
                title=title,
                confidence=0.85 if matched_selector else 0.6,  # Lower confidence for fallback
            )

        except (SelectorNotFoundError, ProductUnavailableError, PageLoadError):
            raise
        except Exception as e:
            logger.error(
                f"Headless fetch failed for {self.store_name} {identifier}: {type(e).__name__}: {e}"
            )
            raise
        finally:
            if page:
                await page.close()

    def _build_url(self, identifier: str) -> str:
        """Build product URL from identifier."""
        return f"{self.base_url}{identifier}"

    @staticmethod
    def _parse_price(price_text: str) -> Decimal:
        """Parse price from text."""
        # Clean up the text
        cleaned = price_text.replace("$", "").replace(",", "").strip()
        
        # Handle ranges like "$10.99 - $15.99" - take the first price
        if " - " in cleaned or " – " in cleaned:
            cleaned = cleaned.split(" - ")[0].split(" – ")[0]
        
        # Extract first number pattern
        match = re.search(r'(\d+(?:\.\d{1,2})?)', cleaned)
        if match:
            try:
                return Decimal(match.group(1))
            except Exception:
                pass
        
        # Fallback: try to parse directly
        parts = cleaned.split()
        if parts:
            cleaned = parts[0]

        try:
            return Decimal(cleaned)
        except Exception:
            raise ValueError(f"Could not parse price from: {price_text}")

    def get_rate_limit(self):
        """Not used with interval-based rate limiting."""
        from src.ingest.base import RateLimitConfig

        return RateLimitConfig(requests_per_second=0.017, burst_size=1)

    def get_store_name(self) -> str:
        """Get the store name."""
        return self.store_name
