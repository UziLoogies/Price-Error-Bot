"""Delta detection for product change tracking.

Tracks which products have changed since last scan to avoid re-processing
unchanged products, improving scan efficiency.
"""

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any

import redis.asyncio as redis

from src.config import settings
from src import metrics

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredProduct:
    """Product discovered during category scan (imported type hint)."""
    sku: str
    url: str
    title: str
    current_price: Decimal
    original_price: Optional[Decimal] = None
    store: str = ""
    image_url: Optional[str] = None
    category_id: Optional[int] = None


class DeltaDetector:
    """
    Detects changes in products between scans using Redis.
    
    Computes a hash of price-relevant fields and compares with stored values
    to determine if a product needs re-processing.
    """
    
    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: Optional[int] = None):
        self.redis_url = redis_url or settings.redis_url
        self.ttl = ttl_seconds or settings.delta_cache_ttl_seconds
        self._redis: Optional[redis.Redis] = None
    
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
    
    def _get_product_key(self, store: str, sku: str) -> str:
        """Generate Redis key for a product."""
        return f"delta:{store}:{sku}"
    
    def compute_product_hash(self, product: Any) -> str:
        """
        Compute hash of price-relevant fields for change detection.
        
        Fields hashed:
        - SKU
        - Current price
        - Original price
        
        Args:
            product: Product object with sku, current_price, original_price
            
        Returns:
            MD5 hash string
        """
        current_price = str(product.current_price) if product.current_price else "0"
        original_price = str(product.original_price) if product.original_price else "0"
        
        data = f"{product.sku}:{current_price}:{original_price}"
        return hashlib.md5(data.encode()).hexdigest()
    
    async def has_changed(self, product: Any, store: str) -> bool:
        """
        Check if a product has changed since last scan.
        
        Args:
            product: Product object
            store: Store identifier
            
        Returns:
            True if product has changed or is new, False if unchanged
        """
        if not settings.delta_detection_enabled:
            return True  # Always process if delta detection is disabled
        
        try:
            redis_client = await self._get_redis()
            key = self._get_product_key(store, product.sku)
            
            current_hash = self.compute_product_hash(product)
            stored_hash = await redis_client.get(key)
            
            if stored_hash is None:
                # New product
                return True
            
            return current_hash != stored_hash
            
        except Exception as e:
            logger.debug(f"Error checking delta for {store}:{product.sku}: {e}")
            return True  # Process on error
    
    async def filter_changed(
        self,
        products: List[Any],
        store: str,
    ) -> List[Any]:
        """
        Filter products to only those with changes.
        
        Args:
            products: List of discovered products
            store: Store identifier
            
        Returns:
            List of products that have changed
        """
        if not settings.delta_detection_enabled:
            return products
        
        if not products:
            return []
        
        try:
            redis_client = await self._get_redis()
            
            # Get all current hashes
            product_hashes = {
                p.sku: self.compute_product_hash(p)
                for p in products
            }
            
            # Get stored hashes in batch
            keys = [self._get_product_key(store, p.sku) for p in products]
            stored_hashes = await redis_client.mget(keys)
            
            # Compare and filter
            changed_products = []
            unchanged_count = 0
            
            for i, product in enumerate(products):
                current_hash = product_hashes[product.sku]
                stored_hash = stored_hashes[i]
                
                if stored_hash is None or current_hash != stored_hash:
                    changed_products.append(product)
                else:
                    unchanged_count += 1
            
            # Record metrics
            if unchanged_count > 0:
                metrics.record_delta_skip(store, unchanged_count)
            if len(changed_products) > 0:
                metrics.record_delta_change(store, len(changed_products))
            
            logger.debug(
                f"Delta filter for {store}: {len(changed_products)}/{len(products)} changed, "
                f"{unchanged_count} skipped"
            )
            
            return changed_products
            
        except Exception as e:
            logger.warning(f"Error in delta filter for {store}: {e}")
            return products  # Return all on error
    
    async def mark_seen(self, products: List[Any], store: str) -> None:
        """
        Mark products as seen with their current hash.
        
        Called after successfully processing products to update stored hashes.
        
        Args:
            products: List of products that were processed
            store: Store identifier
        """
        if not settings.delta_detection_enabled:
            return
        
        if not products:
            return
        
        try:
            redis_client = await self._get_redis()
            
            # Use pipeline for efficiency
            async with redis_client.pipeline() as pipe:
                for product in products:
                    key = self._get_product_key(store, product.sku)
                    product_hash = self.compute_product_hash(product)
                    await pipe.setex(key, self.ttl, product_hash)
                
                await pipe.execute()
            
            logger.debug(f"Marked {len(products)} products as seen for {store}")
            
        except Exception as e:
            logger.warning(f"Error marking products as seen for {store}: {e}")
    
    async def invalidate(self, store: str, sku: str) -> None:
        """
        Invalidate delta cache for a specific product.
        
        Args:
            store: Store identifier
            sku: Product SKU
        """
        try:
            redis_client = await self._get_redis()
            key = self._get_product_key(store, sku)
            await redis_client.delete(key)
            logger.debug(f"Invalidated delta cache for {store}:{sku}")
            
        except Exception as e:
            logger.debug(f"Error invalidating delta cache: {e}")
    
    async def invalidate_store(self, store: str) -> int:
        """
        Invalidate all delta cache entries for a store.
        
        Args:
            store: Store identifier
            
        Returns:
            Number of entries invalidated
        """
        try:
            redis_client = await self._get_redis()
            pattern = f"delta:{store}:*"
            
            keys = []
            async for key in redis_client.scan_iter(pattern):
                keys.append(key)
            
            if keys:
                await redis_client.delete(*keys)
            
            logger.info(f"Invalidated {len(keys)} delta cache entries for {store}")
            return len(keys)
            
        except Exception as e:
            logger.warning(f"Error invalidating delta cache for {store}: {e}")
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get delta detection statistics.
        
        Returns:
            Dict with statistics
        """
        try:
            redis_client = await self._get_redis()
            
            # Count cache entries by store
            store_counts: Dict[str, int] = {}
            async for key in redis_client.scan_iter("delta:*"):
                parts = key.split(":")
                if len(parts) >= 2:
                    store = parts[1]
                    store_counts[store] = store_counts.get(store, 0) + 1
            
            return {
                "total_entries": sum(store_counts.values()),
                "entries_by_store": store_counts,
                "ttl_seconds": self.ttl,
                "enabled": settings.delta_detection_enabled,
            }
            
        except Exception as e:
            logger.debug(f"Error getting delta stats: {e}")
            return {
                "error": str(e),
                "enabled": settings.delta_detection_enabled,
            }


# Global instance
delta_detector = DeltaDetector()
