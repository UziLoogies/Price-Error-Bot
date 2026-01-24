"""Internal JSON endpoint fetcher for structured price data."""

import json
import logging
import re
from decimal import Decimal
from urllib.parse import urlparse

import httpx

from src.config import settings
from src.ingest.base import BaseFetcher, RawPriceData
from src.ingest.rate_limiter import rate_limiter
from src.ingest.session_manager import session_manager

logger = logging.getLogger(__name__)


class JSONEndpointFetcher(BaseFetcher):
    """Fetcher for internal JSON endpoints exposed by retailer frontends."""

    def __init__(
        self,
        store_name: str,
        base_url: str,
        endpoint_template: str,
        price_path: str,
        title_path: str | None = None,
        extract_from_html: bool = False,
        json_selector: str | None = None,
    ):
        """
        Initialize JSON endpoint fetcher.

        Args:
            store_name: Store identifier
            base_url: Base URL for product pages or API
            endpoint_template: URL template with {identifier} placeholder
            price_path: JSON path to price (e.g., "priceInfo.currentPrice.price")
            title_path: Optional JSON path to title
            extract_from_html: If True, extract JSON from HTML page source
            json_selector: If extract_from_html, selector/pattern to find JSON
        """
        self.store_name = store_name
        self.base_url = base_url
        self.endpoint_template = endpoint_template
        self.price_path = price_path.split(".")
        self.title_path = title_path.split(".") if title_path else None
        self.extract_from_html = extract_from_html
        self.json_selector = json_selector
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with cookies."""
        if self._http_client is None:
            cookies = session_manager.load_cookies(self.store_name)
            cookie_dict = {}
            for cookie in cookies:
                cookie_dict[cookie["name"]] = cookie["value"]

            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                },
                cookies=cookie_dict,
            )
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def fetch(self, identifier: str) -> RawPriceData:
        """
        Fetch price from JSON endpoint.

        Args:
            identifier: Product SKU/ID

        Returns:
            RawPriceData with price information
        """
        client = await self._get_client()

        if self.extract_from_html:
            # Fetch HTML page and extract embedded JSON
            url = self._build_product_url(identifier)
            json_data = await self._extract_json_from_html(client, url)
        else:
            # Direct JSON endpoint call
            url = self._build_endpoint_url(identifier)
            json_data = await self._fetch_json(client, url)

        domain = urlparse(url).netloc

        # Rate limit
        rate_config = settings.retailer_rate_limits.get(self.store_name, {})
        min_interval = rate_config.get("min_interval", 20)
        max_interval = rate_config.get("max_interval", 30)
        jitter = rate_config.get("jitter", 5)

        await rate_limiter.acquire_with_interval(
            domain, min_interval, max_interval, jitter
        )

        # Extract price using JSON path
        current_price = self._extract_path(json_data, self.price_path)

        # Extract title if path provided
        title = None
        if self.title_path:
            title = self._extract_path(json_data, self.title_path)

        return RawPriceData(
            sku=identifier,
            url=self._build_product_url(identifier) if self.extract_from_html else url,
            store=self.store_name,
            current_price=Decimal(str(current_price)) if current_price else None,
            msrp=None,
            title=str(title) if title else None,
            confidence=0.9,
        )

    def _build_product_url(self, identifier: str) -> str:
        """Build product page URL."""
        return f"{self.base_url}{identifier}"

    def _build_endpoint_url(self, identifier: str) -> str:
        """Build JSON endpoint URL."""
        return self.endpoint_template.format(identifier=identifier, base=self.base_url)

    async def _fetch_json(self, client: httpx.AsyncClient, url: str) -> dict:
        """Fetch JSON from endpoint."""
        response = await client.get(url)
        response.raise_for_status()
        session_manager.update_cookies_from_response(self.store_name, response)
        return response.json()

    async def _extract_json_from_html(
        self, client: httpx.AsyncClient, url: str
    ) -> dict:
        """Extract embedded JSON from HTML page."""
        response = await client.get(url)
        response.raise_for_status()
        session_manager.update_cookies_from_response(self.store_name, response)

        html = response.text

        if self.json_selector:
            # Pattern-based extraction (e.g., `__TGT_DATA__ = {...}`)
            pattern = re.compile(
                rf"{re.escape(self.json_selector)}\s*=\s*(\{{.*?\}})", re.DOTALL
            )
            match = pattern.search(html)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
        else:
            # Try to find script tags with JSON
            pattern = re.compile(r"<script[^>]*>(\{.*?\})</script>", re.DOTALL)
            matches = pattern.findall(html)
            for match in matches:
                try:
                    data = json.loads(match)
                    # Check if it contains price data
                    if self._has_path(data, self.price_path):
                        return data
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"Could not extract JSON from HTML for {url}")

    def _extract_path(self, data: dict, path: list[str]):
        """Extract value from nested dict using path."""
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current

    def _has_path(self, data: dict, path: list[str]) -> bool:
        """Check if path exists in data."""
        current = data
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return False
        return True

    def get_rate_limit(self):
        """Not used with interval-based rate limiting."""
        from src.ingest.base import RateLimitConfig

        return RateLimitConfig(requests_per_second=0.033, burst_size=1)

    def get_store_name(self) -> str:
        """Get the store name."""
        return self.store_name
