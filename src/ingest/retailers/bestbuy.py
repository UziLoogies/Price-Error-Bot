"""Best Buy price fetcher using static HTML with JSON fallback."""

import logging
from decimal import Decimal

from src.ingest.base import RawPriceData
from src.ingest.fetchers.static import StaticHTMLFetcher
from src.ingest.rate_limiter import rate_limiter
from src.ingest.session_manager import session_manager

logger = logging.getLogger(__name__)


class BestBuyFetcher(StaticHTMLFetcher):
    """Fetch Best Buy prices from static HTML or embedded JSON."""

    def __init__(self):
        super().__init__(
            store_name="bestbuy",
            base_url="https://www.bestbuy.com/site/",
            price_selector=".priceView-customer-price span",
            title_selector="h1.heading-5",
        )

    async def fetch(self, identifier: str) -> RawPriceData:
        """Fetch with JSON fallback if HTML parsing fails."""
        try:
            return await super().fetch(identifier)
        except Exception as e:
            logger.debug(f"Static HTML fetch failed, trying JSON fallback: {e}")
            # Try JSON endpoint fallback
            return await self._fetch_json_fallback(identifier)

    async def _fetch_json_fallback(self, identifier: str) -> RawPriceData:
        """Fallback to internal JSON endpoint."""
        from urllib.parse import urlparse

        import httpx

        client = await self._get_client()
        url = f"https://www.bestbuy.com/api/3.0/priceBlocks?skus={identifier}"
        domain = urlparse(url).netloc

        rate_config = self._get_rate_config()
        await rate_limiter.acquire_with_interval(
            domain,
            rate_config["min_interval"],
            rate_config["max_interval"],
            rate_config["jitter"],
        )

        response = await client.get(url)
        response.raise_for_status()
        session_manager.update_cookies_from_response(self.store_name, response)

        data = response.json()
        price_info = data.get("skus", [{}])[0].get("price", {})
        current_price = Decimal(str(price_info.get("currentPrice", 0)))

        return RawPriceData(
            sku=identifier,
            url=self._build_url(identifier),
            store=self.store_name,
            current_price=current_price,
            msrp=None,
            confidence=0.9,
        )

    def _get_rate_config(self):
        """Get retailer rate config."""
        from src.config import settings

        return settings.retailer_rate_limits.get(self.store_name, {
            "min_interval": 15,
            "max_interval": 30,
            "jitter": 5,
        })
