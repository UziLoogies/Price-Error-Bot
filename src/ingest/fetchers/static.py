"""Static HTML fetcher for server-rendered price data."""

import asyncio
import logging
import random
import re
from decimal import Decimal
from typing import Optional, List, Union, Tuple
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from src.config import settings
from src.ingest.base import BaseFetcher, RawPriceData
from src.ingest.rate_limiter import rate_limiter
from src.ingest.session_manager import session_manager
from src.ingest.proxy_manager import proxy_rotator, ProxyInfo

logger = logging.getLogger(__name__)

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class StaticHTMLFetcher(BaseFetcher):
    """Fetcher for static HTML pages with server-rendered prices and proxy support."""

    def __init__(
        self,
        store_name: str,
        base_url: str,
        price_selector: Union[str, List[str]],
        title_selector: str | None = None,
        original_price_selector: Union[str, List[str], None] = None,
        use_proxy: bool = True,
    ):
        """
        Initialize static HTML fetcher.

        Args:
            store_name: Store identifier
            base_url: Base URL for product pages
            price_selector: CSS selector(s) for price element - can be string or list
            title_selector: Optional CSS selector for product title
            original_price_selector: Optional CSS selector(s) for strikethrough/was price
            use_proxy: Whether to use rotating proxies
        """
        self.store_name = store_name
        self.base_url = base_url
        self.title_selector = title_selector
        self.use_proxy = use_proxy
        
        # Parse selectors into lists
        self.price_selectors = self._parse_selectors(price_selector)
        self.original_price_selectors = self._parse_selectors(original_price_selector) if original_price_selector else []
        
        # Keep legacy attributes for compatibility
        self.price_selector = price_selector if isinstance(price_selector, str) else ", ".join(self.price_selectors)
        self.original_price_selector = original_price_selector
        
        self._http_clients: dict[int, httpx.AsyncClient] = {}  # proxy_id -> client
        self._default_client: Optional[httpx.AsyncClient] = None

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
    
    def _try_selectors(
        self, 
        parser: HTMLParser, 
        selectors: List[str]
    ) -> Tuple[Optional[str], Optional[any]]:
        """
        Try multiple selectors and return the first one that matches.
        
        Args:
            parser: HTMLParser instance
            selectors: List of CSS selectors to try
            
        Returns:
            Tuple of (successful_selector, element) or (None, None)
        """
        for i, selector in enumerate(selectors):
            try:
                elem = parser.css_first(selector)
                if elem:
                    logger.debug(f"Selector {i+1}/{len(selectors)} matched: {selector[:50]}...")
                    return selector, elem
            except Exception as e:
                logger.debug(f"Selector {i+1}/{len(selectors)} error: {selector[:50]}... - {e}")
                continue
        
        return None, None

    async def _get_client(self, proxy: Optional[ProxyInfo] = None) -> httpx.AsyncClient:
        """
        Get or create HTTP client with cookies and optional proxy.
        
        Args:
            proxy: Optional proxy to use
        """
        cookies = session_manager.load_cookies(self.store_name)
        cookie_dict = {}
        for cookie in cookies:
            cookie_dict[cookie["name"]] = cookie["value"]

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        if proxy:
            if proxy.id not in self._http_clients:
                logger.debug(f"Creating HTTP client with proxy {proxy.host}:{proxy.port}")
                self._http_clients[proxy.id] = httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                    headers=headers,
                    cookies=cookie_dict,
                    proxy=proxy.url,
                )
            return self._http_clients[proxy.id]

        if self._default_client is None:
            self._default_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=headers,
                cookies=cookie_dict,
            )
        return self._default_client

    async def close(self):
        """Close HTTP clients."""
        for proxy_id, client in self._http_clients.items():
            try:
                await client.aclose()
            except Exception as e:
                logger.error(f"Error closing proxy client {proxy_id}: {e}")
        self._http_clients.clear()

        if self._default_client:
            await self._default_client.aclose()
            self._default_client = None

    async def fetch(self, identifier: str, proxy_type: Optional[str] = None) -> RawPriceData:
        """
        Fetch price from static HTML page with retry and proxy rotation.

        Args:
            identifier: Product SKU/ID
            proxy_type: Optional proxy type (datacenter/residential/isp)

        Returns:
            RawPriceData with price information
        """
        max_retries = 3
        last_error = None
        current_proxy: Optional[ProxyInfo] = None

        for attempt in range(max_retries):
            try:
                # Get a proxy for this attempt if enabled
                if self.use_proxy and proxy_rotator.has_proxies(proxy_type=proxy_type):
                    current_proxy = await proxy_rotator.get_next_proxy(proxy_type=proxy_type)
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

            except Exception as e:
                last_error = e

                # Report failure to proxy rotator
                if current_proxy:
                    await proxy_rotator.report_failure(current_proxy.id)

                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2 + random.uniform(0, 2)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {self.store_name} {identifier} "
                        f"after {wait_time:.1f}s: {e}"
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
        """
        client = await self._get_client(proxy)
        url = self._build_url(identifier)
        domain = urlparse(url).netloc

        # Rate limit with retailer-specific intervals
        rate_config = settings.retailer_rate_limits.get(self.store_name, {})
        min_interval = rate_config.get("min_interval", 20)
        max_interval = rate_config.get("max_interval", 30)
        jitter = rate_config.get("jitter", 5)

        await rate_limiter.acquire_with_interval(
            domain, min_interval, max_interval, jitter
        )

        try:
            response = await client.get(url)
            response.raise_for_status()

            # Update cookies from response
            session_manager.update_cookies_from_response(self.store_name, response)

            # Parse HTML
            parser = HTMLParser(response.text)

            # Try all price selectors
            logger.debug(f"Trying {len(self.price_selectors)} price selectors for {identifier}")
            matched_selector, price_elem = self._try_selectors(parser, self.price_selectors)
            
            if not price_elem:
                # Try fallback regex extraction
                current_price = self._extract_price_fallback(response.text)
                if not current_price:
                    raise ValueError(
                        f"None of {len(self.price_selectors)} price selectors found for {identifier}"
                    )
                matched_selector = "fallback_regex"
            else:
                price_text = price_elem.text(strip=True)
                current_price = self._parse_price(price_text)

            logger.debug(
                f"Price found for {identifier}: ${current_price} "
                f"(selector: {matched_selector[:40] if matched_selector else 'fallback'}...)"
            )

            # Extract original/strikethrough price if selectors provided
            original_price = None
            if self.original_price_selectors:
                _, orig_elem = self._try_selectors(parser, self.original_price_selectors)
                if orig_elem:
                    try:
                        orig_text = orig_elem.text(strip=True)
                        original_price = self._parse_price(orig_text)
                    except Exception:
                        pass  # Original price is optional

            # Extract title if selector provided
            title = None
            if self.title_selector:
                title_elem = parser.css_first(self.title_selector)
                if title_elem:
                    title = title_elem.text(strip=True)

            return RawPriceData(
                sku=identifier,
                url=url,
                store=self.store_name,
                current_price=current_price,
                msrp=original_price,
                title=title,
                confidence=0.9 if matched_selector != "fallback_regex" else 0.7,
            )

        except Exception as e:
            logger.error(f"Static fetch failed for {self.store_name} {identifier}: {e}")
            raise
    
    def _extract_price_fallback(self, html: str) -> Optional[Decimal]:
        """
        Fallback price extraction using regex on HTML content.
        
        Args:
            html: Raw HTML content
            
        Returns:
            Extracted price or None
        """
        # Look for price patterns
        patterns = [
            r'\$(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)',  # $XX.XX or $X,XXX.XX
            r'"price":\s*"?\$?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)"?',
            r'"currentPrice":\s*(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html)
            if matches:
                for match in matches:
                    try:
                        price = Decimal(match.replace(",", ""))
                        if Decimal("0.01") <= price <= Decimal("50000"):
                            logger.debug(f"Fallback regex extracted price: ${price}")
                            return price
                    except:
                        continue
        
        return None

    def _build_url(self, identifier: str) -> str:
        """Build product URL from identifier."""
        return f"{self.base_url}{identifier}"

    @staticmethod
    def _parse_price(price_text: str) -> Decimal:
        """
        Parse price from text (removes $, commas, etc.).

        Args:
            price_text: Raw price text

        Returns:
            Decimal price
        """
        # Remove currency symbols, commas, whitespace
        cleaned = price_text.replace("$", "").replace(",", "").strip()
        # Extract first number (handle ranges like "$10 - $20")
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

        return RateLimitConfig(requests_per_second=0.033, burst_size=1)

    def get_store_name(self) -> str:
        """Get the store name."""
        return self.store_name
