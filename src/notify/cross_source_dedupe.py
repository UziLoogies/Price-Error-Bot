"""Cross-source deduplication for deal aggregators.

When the same product is found on multiple deal sources (SaveYourDeals, Slickdeals, Woot),
we only want to notify for the best price. This module tracks products across sources
and ensures only the best deal gets notified.
"""

import hashlib
import logging
import re
from decimal import Decimal
from typing import Optional

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)


# Stores that are considered deal aggregators (may list products from other retailers)
AGGREGATOR_STORES = {"saveyourdeals", "slickdeals", "woot"}

# Pattern to extract ASIN from various URL formats
ASIN_PATTERN = re.compile(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', re.IGNORECASE)


class CrossSourceDeduper:
    """
    Manages cross-source deduplication for deal alerts.
    
    When the same product (identified by normalized SKU/ASIN) appears on multiple
    deal aggregator sites, only notify for the best (lowest) price.
    
    Uses Redis to track recently seen products with a short TTL (scan interval + buffer).
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: redis.Redis | None = None
        # TTL should be slightly longer than scan interval to catch duplicates
        # Default: 10 minutes (scan interval 5min + 5min buffer)
        self.ttl_seconds = 600
    
    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    def _normalize_sku(self, sku: str, url: str) -> str:
        """
        Normalize SKU to allow cross-source matching.
        
        For Amazon products (ASINs), extracts the ASIN from the URL if possible.
        For other products, uses the original SKU.
        
        Args:
            sku: The product SKU
            url: The product URL
            
        Returns:
            Normalized SKU for cross-source comparison
        """
        # Check if this is an Amazon ASIN (10 alphanumeric characters)
        if re.match(r'^[A-Z0-9]{10}$', sku, re.IGNORECASE):
            return f"asin:{sku.upper()}"
        
        # Try to extract ASIN from URL (for affiliate links)
        if url and 'amazon.com' in url.lower():
            match = ASIN_PATTERN.search(url)
            if match:
                return f"asin:{match.group(1).upper()}"
        
        # For non-Amazon products, return as-is with hash for uniqueness
        return f"sku:{sku}"
    
    def _get_cross_source_key(self, normalized_sku: str) -> str:
        """Generate Redis key for cross-source tracking."""
        key_hash = hashlib.md5(normalized_sku.encode()).hexdigest()
        return f"xsource:{key_hash}"
    
    async def should_notify(
        self, 
        sku: str, 
        store: str, 
        price: Decimal,
        url: str = ""
    ) -> bool:
        """
        Check if we should notify for this deal.
        
        Returns True if:
        - This is the first time we've seen this product, OR
        - This price is better (lower) than previously seen prices
        
        Args:
            sku: Product SKU
            store: Store name
            price: Current price
            url: Product URL (used for ASIN extraction)
            
        Returns:
            True if we should notify, False if a better deal exists
        """
        # Only apply cross-source deduplication to aggregator stores
        if store not in AGGREGATOR_STORES:
            return True
        
        try:
            redis_client = await self._get_redis()
            normalized_sku = self._normalize_sku(sku, url)
            key = self._get_cross_source_key(normalized_sku)
            
            # Get existing best price
            existing = await redis_client.get(key)
            
            if existing is None:
                # First time seeing this product, record it
                await self._record_price(key, store, price)
                logger.debug(
                    f"Cross-source: First sighting of {normalized_sku} at ${price} from {store}"
                )
                return True
            
            # Parse existing entry: "store:price"
            try:
                existing_store, existing_price_str = existing.split(":", 1)
                existing_price = Decimal(existing_price_str)
            except (ValueError, TypeError):
                # Invalid format, treat as new
                await self._record_price(key, store, price)
                return True
            
            # Check if this is a better price
            if price < existing_price:
                # This is a better deal, update and notify
                await self._record_price(key, store, price)
                logger.info(
                    f"Cross-source: Better price found! {normalized_sku} at ${price} from {store} "
                    f"(was ${existing_price} from {existing_store})"
                )
                return True
            elif price == existing_price and store != existing_store:
                # Same price from different source, skip to avoid duplicate
                logger.debug(
                    f"Cross-source: Same price ${price} for {normalized_sku} from {store}, "
                    f"already seen from {existing_store}"
                )
                return False
            else:
                # Worse price, skip
                logger.debug(
                    f"Cross-source: Skipping {normalized_sku} at ${price} from {store}, "
                    f"better price ${existing_price} available from {existing_store}"
                )
                return False
                
        except Exception as e:
            logger.error(f"Cross-source deduplication error: {e}")
            # On error, allow notification to avoid missing deals
            return True
    
    async def _record_price(self, key: str, store: str, price: Decimal) -> None:
        """Record the best price for a product."""
        redis_client = await self._get_redis()
        value = f"{store}:{price}"
        await redis_client.setex(key, self.ttl_seconds, value)
    
    async def get_best_price(self, sku: str, url: str = "") -> Optional[tuple[str, Decimal]]:
        """
        Get the best known price for a product.
        
        Args:
            sku: Product SKU
            url: Product URL (for ASIN extraction)
            
        Returns:
            Tuple of (store, price) or None if not tracked
        """
        try:
            redis_client = await self._get_redis()
            normalized_sku = self._normalize_sku(sku, url)
            key = self._get_cross_source_key(normalized_sku)
            
            existing = await redis_client.get(key)
            if existing:
                store, price_str = existing.split(":", 1)
                return (store, Decimal(price_str))
        except Exception as e:
            logger.error(f"Error getting best price: {e}")
        
        return None
    
    async def clear_product(self, sku: str, url: str = "") -> None:
        """
        Clear tracking for a product.
        
        Useful when a deal expires or is no longer valid.
        
        Args:
            sku: Product SKU
            url: Product URL
        """
        try:
            redis_client = await self._get_redis()
            normalized_sku = self._normalize_sku(sku, url)
            key = self._get_cross_source_key(normalized_sku)
            await redis_client.delete(key)
            logger.debug(f"Cleared cross-source tracking for {normalized_sku}")
        except Exception as e:
            logger.error(f"Error clearing product: {e}")


# Global instance for convenience
cross_source_deduper = CrossSourceDeduper()
