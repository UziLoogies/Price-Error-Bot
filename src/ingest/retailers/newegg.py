"""Newegg price fetcher using static HTML with embedded JSON fallback."""

import json
import logging
import re
from typing import Optional

from src.ingest.base import RawPriceData
from src.ingest.fetchers.static import StaticHTMLFetcher
from src.ingest.rate_limiter import rate_limiter
from src.ingest.session_manager import session_manager

logger = logging.getLogger(__name__)


class NeweggFetcher(StaticHTMLFetcher):
    """Fetch Newegg prices from static HTML or embedded JSON."""

    def __init__(self):
        super().__init__(
            store_name="newegg",
            base_url="https://www.newegg.com/",
            price_selector=".price-current",
            title_selector="h1.product-title",
        )

    async def fetch(self, identifier: str, proxy_type: Optional[str] = None) -> RawPriceData:
        """Fetch with embedded JSON extraction as fallback."""
        from decimal import Decimal
        from urllib.parse import urlparse

        import httpx

        client = await self._get_client()
        url = self._build_url(identifier)
        domain = urlparse(url).netloc

        rate_config = self._get_rate_config()
        await rate_limiter.acquire_with_interval(
            domain,
            rate_config["min_interval"],
            rate_config["max_interval"],
            rate_config["jitter"],
        )

        try:
            # Try static HTML first
            return await super().fetch(identifier, proxy_type=proxy_type)
        except Exception as e:
            logger.debug(f"Static HTML failed, trying embedded JSON: {e}")

            # Fallback: extract from embedded JSON in page
            response = await client.get(url)
            response.raise_for_status()
            session_manager.update_cookies_from_response(self.store_name, response)

            # Look for product.price in script tags
            html = response.text
            pattern = re.compile(r'"current_price"\s*:\s*"([^"]+)"')
            match = pattern.search(html)

            if match:
                price_text = match.group(1).replace(",", "")
                current_price = Decimal(price_text)

                # Extract title
                title_pattern = re.compile(r'<h1[^>]*>([^<]+)</h1>')
                title_match = title_pattern.search(html)
                title = title_match.group(1).strip() if title_match else None

                return RawPriceData(
                    sku=identifier,
                    url=url,
                    store=self.store_name,
                    current_price=current_price,
                    msrp=None,
                    title=title,
                    confidence=0.85,
                )

            raise

    def _get_rate_config(self):
        """Get retailer rate config."""
        from src.config import settings

        return settings.retailer_rate_limits.get(self.store_name, {
            "min_interval": 15,
            "max_interval": 20,
            "jitter": 3,
        })
