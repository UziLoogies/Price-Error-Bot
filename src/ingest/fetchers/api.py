"""Mobile/Legacy API fetcher for structured data.

Supports mobile app APIs and legacy endpoints that return
structured data (JSON/XML) for faster bulk price fetching.
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import httpx

from src.config import settings
from src.ingest.base import BaseFetcher, RawPriceData
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class APIFetcher(BaseFetcher):
    """
    Fetches product data from mobile/legacy APIs.
    
    Features:
    - Support for mobile app APIs (JSON endpoints)
    - Legacy API endpoints for structured data
    - Faster bulk price fetching via APIs vs HTML scraping
    - Fallback to HTML scraping if API unavailable
    """
    
    def __init__(self, store_name: str, api_endpoint: str):
        """
        Initialize API fetcher.
        
        Args:
            store_name: Store identifier
            api_endpoint: Base API endpoint URL
        """
        self.store_name = store_name
        self.api_endpoint = api_endpoint
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                    "Accept": "application/json",
                },
            )
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def fetch(self, sku: str, proxy_type: Optional[str] = None) -> RawPriceData:
        """
        Fetch product data from API.

        Args:
            sku: Product SKU/identifier
            proxy_type: Optional proxy type (unused)
            
        Returns:
            RawPriceData with price information
        """
        client = await self._get_client()
        domain = urlparse(self.api_endpoint).netloc
        
        # Rate limit
        await rate_limiter.acquire_adaptive(domain)
        
        try:
            # Build API URL (format varies by store)
            api_url = f"{self.api_endpoint.rstrip('/')}/{sku}"
            
            response = await client.get(api_url, timeout=10.0)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract price data (format varies by API)
            current_price = self._extract_price(data)
            original_price = self._extract_original_price(data)
            msrp = self._extract_msrp(data)
            title = self._extract_title(data)
            url = self._extract_url(data, sku)
            availability = self._extract_availability(data)
            
            return RawPriceData(
                sku=sku,
                url=url,
                store=self.store_name,
                current_price=current_price,
                original_price=original_price,
                msrp=msrp,
                title=title,
                availability=availability,
            )
        
        except httpx.HTTPStatusError as e:
            logger.warning(f"API fetch failed for {sku}: HTTP {e.response.status_code}")
            raise
        except Exception as e:
            logger.warning(f"API fetch failed for {sku}: {e}")
            raise
    
    def _extract_price(self, data: Dict[str, Any]) -> Optional[Decimal]:
        """Extract current price from API response."""
        # Common price field names
        price_fields = ["price", "current_price", "sale_price", "final_price", "amount"]
        
        for field in price_fields:
            if field in data:
                price = data[field]
                if isinstance(price, (int, float)):
                    return Decimal(str(price))
                elif isinstance(price, str):
                    # Remove currency symbols
                    price = price.replace("$", "").replace(",", "").strip()
                    try:
                        return Decimal(price)
                    except Exception:
                        pass
        
        return None
    
    def _extract_original_price(self, data: Dict[str, Any]) -> Optional[Decimal]:
        """Extract original/strikethrough price from API response."""
        # Common original price field names
        price_fields = ["original_price", "list_price", "regular_price", "was_price"]
        
        for field in price_fields:
            if field in data:
                price = data[field]
                if isinstance(price, (int, float)):
                    return Decimal(str(price))
                elif isinstance(price, str):
                    price = price.replace("$", "").replace(",", "").strip()
                    try:
                        return Decimal(price)
                    except Exception:
                        pass
        
        return None
    
    def _extract_msrp(self, data: Dict[str, Any]) -> Optional[Decimal]:
        """Extract MSRP from API response."""
        if "msrp" in data:
            msrp = data["msrp"]
            if isinstance(msrp, (int, float)):
                return Decimal(str(msrp))
            elif isinstance(msrp, str):
                msrp = msrp.replace("$", "").replace(",", "").strip()
                try:
                    return Decimal(msrp)
                except Exception:
                    pass
        
        return None
    
    def _extract_title(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract product title from API response."""
        title_fields = ["title", "name", "product_name", "display_name"]
        
        for field in title_fields:
            if field in data:
                return str(data[field])
        
        return None
    
    def _extract_url(self, data: Dict[str, Any], sku: str) -> str:
        """Extract product URL from API response."""
        if "url" in data:
            return str(data["url"])
        if "link" in data:
            return str(data["link"])
        
        # Fallback: construct URL from store base
        return f"{self.api_endpoint.rstrip('/')}/{sku}"
    
    def _extract_availability(self, data: Dict[str, Any]) -> str:
        """Extract availability status from API response."""
        availability_fields = ["availability", "in_stock", "stock_status", "status"]
        
        for field in availability_fields:
            if field in data:
                status = str(data[field]).lower()
                if "in stock" in status or status == "true" or status == "1":
                    return "in_stock"
                elif "out of stock" in status or status == "false" or status == "0":
                    return "out_of_stock"
        
        return "unknown"
    
    async def fetch_bulk(self, skus: list[str]) -> Dict[str, RawPriceData]:
        """
        Fetch multiple products in bulk (if API supports it).
        
        Args:
            skus: List of SKUs to fetch
            
        Returns:
            Dict mapping SKU to RawPriceData
        """
        results = {}
        
        # Try bulk endpoint first
        try:
            client = await self._get_client()
            bulk_url = f"{self.api_endpoint.rstrip('/')}/bulk"
            
            response = await client.post(
                bulk_url,
                json={"skus": skus},
                timeout=30.0,
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Parse bulk response
            for item in data.get("products", []):
                sku = item.get("sku") or item.get("id")
                if sku:
                    results[sku] = RawPriceData(
                        sku=sku,
                        url=self._extract_url(item, sku),
                        store=self.store_name,
                        current_price=self._extract_price(item),
                        original_price=self._extract_original_price(item),
                        msrp=self._extract_msrp(item),
                        title=self._extract_title(item),
                        availability=self._extract_availability(item),
                    )
            
            return results
        
        except Exception as e:
            logger.debug(f"Bulk fetch not supported, falling back to individual: {e}")
        
        # Fallback to individual fetches
        for sku in skus:
            try:
                results[sku] = await self.fetch(sku)
            except Exception as e:
                logger.debug(f"Failed to fetch {sku}: {e}")
        
        return results


# Note: This fetcher would need to be registered in the fetcher registry
# for specific stores that have API endpoints available
