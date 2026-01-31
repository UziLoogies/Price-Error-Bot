"""Search API scanner for hidden deal discovery.

Queries site search endpoints with price filters to discover
deals that might not appear on category pages.
"""

import logging
from decimal import Decimal
from typing import List, Optional, Dict
from urllib.parse import urlparse, urlencode

import httpx

from src.config import settings
from src.ingest.category_scanner import DiscoveredProduct
from src.ingest.proxy_manager import proxy_rotator
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class SearchScanner:
    """
    Scans search APIs to find hidden deals.
    
    Features:
    - Query site search endpoints with price filters
    - Sort by price (ascending) to find lowest-priced items
    - Use keyword combinations (alphabet, common terms)
    - Discover "hidden" deals not on category pages
    - Support both official and unofficial search APIs
    """
    
    def __init__(self):
        """Initialize search scanner."""
        self.enabled = getattr(settings, 'search_api_enabled', True)
        self.max_price_filter = Decimal(str(getattr(settings, 'search_max_price_filter', 10.0)))
        self.keyword_combinations = getattr(
            settings,
            'search_keyword_combinations',
            list("abcdefghijklmnopqrstuvwxyz0123456789"),
        )
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    def _get_search_endpoint(self, store: str) -> Optional[str]:
        """
        Get search API endpoint for a store.
        
        Args:
            store: Store identifier
            
        Returns:
            Search endpoint URL or None
        """
        # Store-specific search endpoints
        endpoints = {
            "amazon_us": "https://www.amazon.com/s",
            "walmart": "https://www.walmart.com/search",
            "target": "https://www.target.com/s",
            "bestbuy": "https://www.bestbuy.com/site/searchpage.jsp",
        }
        
        return endpoints.get(store)
    
    async def search_by_price(
        self,
        store: str,
        max_price: Optional[Decimal] = None,
    ) -> List[DiscoveredProduct]:
        """
        Search for products with price filter.
        
        Args:
            store: Store identifier
            max_price: Maximum price filter
            
        Returns:
            List of DiscoveredProduct objects
        """
        if not self.enabled:
            return []
        
        max_price = max_price or self.max_price_filter
        endpoint = self._get_search_endpoint(store)
        
        if not endpoint:
            logger.debug(f"No search endpoint configured for {store}")
            return []
        
        client = await self._get_client()
        domain = urlparse(endpoint).netloc
        
        # Rate limit
        await rate_limiter.acquire_adaptive(domain)
        
        try:
            # Build search query with price filter
            params = {
                "k": "",  # Empty keyword
                "rh": f"p_36:{int(max_price * 100)}-",  # Price filter (varies by site)
                "sort": "price-asc-rank",  # Sort by price ascending
            }
            
            url = f"{endpoint}?{urlencode(params)}"
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            
            # Parse results (would need store-specific parser)
            # For now, return empty list (can be enhanced with parsers)
            logger.debug(f"Searched {store} for products <${max_price}")
            return []
        
        except Exception as e:
            logger.error(f"Error searching {store} by price: {e}")
            return []
    
    async def search_keywords(
        self,
        store: str,
        keywords: List[str],
    ) -> List[DiscoveredProduct]:
        """
        Search using keyword combinations.
        
        Args:
            store: Store identifier
            keywords: List of keywords to search
            
        Returns:
            List of DiscoveredProduct objects
        """
        if not self.enabled:
            return []
        
        endpoint = self._get_search_endpoint(store)
        if not endpoint:
            return []
        
        client = await self._get_client()
        domain = urlparse(endpoint).netloc
        
        all_products = []
        
        for keyword in keywords[:10]:  # Limit to avoid overload
            try:
                # Rate limit
                await rate_limiter.acquire_adaptive(domain)
                
                params = {
                    "k": keyword,
                    "sort": "price-asc-rank",  # Sort by price
                }
                
                url = f"{endpoint}?{urlencode(params)}"
                response = await client.get(url, timeout=30.0)
                response.raise_for_status()
                
                # Parse results (would need store-specific parser)
                # For now, skip parsing
                logger.debug(f"Searched {store} with keyword: {keyword}")
            
            except Exception as e:
                logger.debug(f"Error searching {store} with keyword {keyword}: {e}")
                continue
        
        return all_products
    
    async def find_penny_deals(
        self,
        store: str,
    ) -> List[DiscoveredProduct]:
        """
        Find penny deals (items priced $0.01-$1.00).
        
        Args:
            store: Store identifier
            
        Returns:
            List of DiscoveredProduct objects
        """
        # Search for items <$1.00
        return await self.search_by_price(store, max_price=Decimal("1.00"))


# Global search scanner instance
search_scanner = SearchScanner()
