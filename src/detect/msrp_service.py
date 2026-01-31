"""MSRP reference service for price validation.

Fetches and caches MSRP values from external APIs (Keepa, product databases)
to enable MSRP-based discount detection and error flagging.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict
from urllib.parse import urlencode

import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Product
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class MSRPService:
    """
    Fetches and manages MSRP (Manufacturer's Suggested Retail Price) data.
    
    Features:
    - Fetch MSRP from external APIs (Keepa, product databases)
    - Cache MSRP values in database
    - Use MSRP for discount calculation when original_price unavailable
    - Flag items >90% off MSRP as potential errors
    """
    
    def __init__(self):
        """Initialize MSRP service."""
        self.cache_ttl_days = getattr(settings, 'msrp_cache_ttl_days', 90)
        self.verification_enabled = getattr(settings, 'msrp_verification_enabled', True)
        self.discount_threshold = getattr(settings, 'msrp_discount_threshold', 0.90)
        self._http_client: Optional[httpx.AsyncClient] = None
        self.keepa_api_key = getattr(settings, 'keepa_api_key', '')
    
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
    
    async def fetch_msrp_from_keepa(self, asin: str) -> Optional[Decimal]:
        """
        Fetch MSRP from Keepa API.
        
        Args:
            asin: Amazon ASIN
            
        Returns:
            MSRP in Decimal or None if not found
        """
        if not self.keepa_api_key:
            return None
        
        try:
            client = await self._get_client()
            
            params = {
                "key": self.keepa_api_key,
                "domain": "1",  # US
                "asin": asin,
                "stats": "90",
                "history": "0",
            }
            
            url = f"https://keepa.com/api/1.0/product?{urlencode(params)}"
            
            response = await client.get(url)
            response.raise_for_status()
            
            data = response.json()
            products = data.get("products", [])
            
            if not products:
                return None
            
            product = products[0]
            list_price = product.get("listPrice", 0)
            
            if list_price and list_price > 0:
                # Keepa prices are in cents
                msrp = Decimal(str(list_price)) / 100
                logger.debug(f"Fetched MSRP from Keepa for {asin}: ${msrp}")
                return msrp
            
            return None
        
        except Exception as e:
            logger.debug(f"Error fetching MSRP from Keepa for {asin}: {e}")
            return None
    
    async def get_msrp(
        self,
        product: Product,
        force_refresh: bool = False,
    ) -> Optional[Decimal]:
        """
        Get MSRP for a product (from cache or API).
        
        Args:
            product: Product to get MSRP for
            force_refresh: Force refresh from API even if cached
            
        Returns:
            MSRP in Decimal or None
        """
        if not self.verification_enabled:
            return product.msrp  # Use existing MSRP if available
        
        # Check if cached MSRP is still valid
        msrp_verified_at = getattr(product, 'msrp_verified_at', None)
        if not force_refresh and msrp_verified_at:
            age_days = (datetime.utcnow() - msrp_verified_at).days
            if age_days < self.cache_ttl_days:
                return product.msrp  # Use cached MSRP
        
        # Try to fetch from Keepa (for Amazon products)
        if product.store == "amazon_us" and product.sku:
            msrp = await self.fetch_msrp_from_keepa(product.sku)
            if msrp:
                # Update product with fetched MSRP
                async with AsyncSessionLocal() as db:
                    db_product = await db.get(Product, product.id)
                    if db_product:
                        db_product.msrp = msrp
                        db_product.msrp_source = "keepa"
                        db_product.msrp_verified_at = datetime.utcnow()
                        await db.commit()
                        logger.debug(f"Updated MSRP for product {product.id}: ${msrp}")
                    return msrp
        
        # Fallback to existing MSRP
        return product.msrp
    
    async def calculate_msrp_discount(
        self,
        current_price: Decimal,
        msrp: Decimal,
    ) -> float:
        """
        Calculate discount percentage from MSRP.
        
        Args:
            current_price: Current price
            msrp: MSRP
            
        Returns:
            Discount percentage (0-100)
        """
        if msrp == 0:
            return 0.0
        
        discount = float((1 - current_price / msrp) * 100)
        return max(0.0, discount)
    
    async def is_anomalous_msrp_discount(
        self,
        current_price: Decimal,
        product: Product,
    ) -> bool:
        """
        Check if discount from MSRP is anomalously high (>90%).
        
        Args:
            current_price: Current price
            product: Product to check
            
        Returns:
            True if discount is anomalously high
        """
        msrp = await self.get_msrp(product)
        if not msrp:
            return False
        
        discount = await self.calculate_msrp_discount(current_price, msrp)
        return discount >= (self.discount_threshold * 100)
    
    async def update_msrp_for_product(
        self,
        product_id: int,
        msrp: Decimal,
        source: str = "manual",
    ) -> None:
        """
        Update MSRP for a product in database.
        
        Args:
            product_id: Product ID
            msrp: MSRP value
            source: Source of MSRP (keepa, manual, etc.)
        """
        async with AsyncSessionLocal() as db:
            product = await db.get(Product, product_id)
            if product:
                product.msrp = msrp
                product.msrp_source = source
                product.msrp_verified_at = datetime.utcnow()
                await db.commit()
                logger.debug(f"Updated MSRP for product {product_id}: ${msrp} (source: {source})")


# Global MSRP service instance
msrp_service = MSRPService()
