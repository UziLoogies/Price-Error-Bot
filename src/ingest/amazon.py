"""Amazon price fetcher using Keepa API or CamelCamelCamel RSS."""

import logging
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

import httpx

from src.config import settings
from src.ingest.base import BaseFetcher, RawPriceData, RateLimitConfig
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class AmazonFetcher(BaseFetcher):
    """Fetch Amazon prices using Keepa API or CamelCamelCamel."""

    def __init__(self):
        self.store_name = "amazon_us"
        self.base_url = "https://www.amazon.com/dp/"
        self._keepa_enabled = bool(settings.keepa_api_key)
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def fetch(self, asin: str) -> RawPriceData:
        """
        Fetch Amazon price data.

        Args:
            asin: Amazon ASIN

        Returns:
            RawPriceData with price information
        """
        # Rate limit
        await rate_limiter.acquire("keepa.com")

        if self._keepa_enabled:
            try:
                return await self._fetch_keepa(asin)
            except Exception as e:
                logger.warning(f"Keepa fetch failed for {asin}: {e}, falling back to CCC")
                return await self._fetch_camelcamelcamel(asin)
        else:
            return await self._fetch_camelcamelcamel(asin)

    async def _fetch_keepa(self, asin: str) -> RawPriceData:
        """Fetch price data from Keepa API."""
        client = await self._get_client()

        # Rate limit for Keepa
        await rate_limiter.acquire("keepa.com", requests_per_second=1.0)

        params = {
            "key": settings.keepa_api_key,
            "domain": "1",  # US
            "asin": asin,
            "stats": "90",  # 90 days
            "history": "0",  # No history needed
        }

        url = f"https://keepa.com/api/1.0/product?{urlencode(params)}"

        response = await client.get(url)
        response.raise_for_status()

        data = response.json()
        products = data.get("products", [])

        if not products:
            raise ValueError(f"No product data found for ASIN {asin}")

        product = products[0]
        csv = product.get("csv", [])

        # Parse CSV data (Keepa uses CSV format)
        # csv[1] = New (Amazon) price
        # csv[3] = Used price
        # csv[2] = Sales rank
        current_price = None
        if len(csv) > 1 and csv[1] and csv[1] > 0:
            # Keepa prices are in cents, last element is most recent
            current_price = Decimal(str(csv[1][-1])) / 100

        msrp = product.get("listPrice", 0)
        if msrp:
            msrp = Decimal(str(msrp)) / 100

        title = product.get("title", "")
        availability = "in_stock" if current_price else "out_of_stock"

        return RawPriceData(
            sku=asin,
            url=f"{self.base_url}{asin}",
            store=self.store_name,
            current_price=current_price,
            msrp=Decimal(str(msrp)) if msrp else None,
            title=title,
            availability=availability,
            confidence=0.9 if current_price else 0.5,
        )

    async def _fetch_camelcamelcamel(self, asin: str) -> RawPriceData:
        """
        Fetch price data from CamelCamelCamel RSS feed.

        This is a fallback method. CCC RSS has limited data.
        """
        client = await self._get_client()

        # Rate limit for CCC
        await rate_limiter.acquire("camelcamelcamel.com", requests_per_second=2.0)

        url = f"https://camelcamelcamel.com/product/{asin}"
        rss_url = f"https://camelcamelcamel.com/product/{asin}.xml"

        try:
            # Try to fetch RSS feed
            response = await client.get(rss_url)
            response.raise_for_status()

            # Parse XML (simple extraction)
            # This is a basic implementation - for production, use proper XML parsing
            text = response.text

            # Extract price from XML (simplified)
            # CCC RSS format varies, this is a basic fallback
            current_price = None
            title = None

            # For now, return a low-confidence result
            # In production, implement proper XML parsing or use Keepa API
            logger.warning(
                f"CCC RSS parsing not fully implemented for {asin}, "
                "consider using Keepa API for better results"
            )

            return RawPriceData(
                sku=asin,
                url=url,
                store=self.store_name,
                current_price=current_price,
                msrp=None,
                title=title,
                availability="unknown",
                confidence=0.3,  # Low confidence for CCC
            )

        except Exception as e:
            logger.error(f"Failed to fetch from CamelCamelCamel for {asin}: {e}")
            raise

    def get_rate_limit(self) -> RateLimitConfig:
        """Get rate limiting configuration."""
        if self._keepa_enabled:
            return RateLimitConfig(
                requests_per_second=1.0,
                burst_size=5,
                backoff_multiplier=2.0,
                max_backoff_seconds=60.0,
            )
        else:
            # More lenient for CCC scraping
            return RateLimitConfig(
                requests_per_second=2.0,
                burst_size=10,
                backoff_multiplier=2.0,
                max_backoff_seconds=60.0,
            )

    def get_store_name(self) -> str:
        """Get the store name."""
        return self.store_name
