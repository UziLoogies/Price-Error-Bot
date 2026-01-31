"""Fresh product prioritizer for new product scanning.

Boosts scan priority for products <24 hours old and adjusts
scan intervals to catch pricing errors on new listings.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from src.config import settings
from src.db.models import Product
from src.ingest.new_product_detector import new_product_detector

logger = logging.getLogger(__name__)


class FreshProductPrioritizer:
    """
    Prioritizes fresh products for scanning.
    
    Features:
    - Boost scan priority for products <24 hours old
    - Adjust scan intervals (scan new products more frequently)
    - Track "new arrivals" sections from category pages
    - Integrate with existing priority-based scanning
    """
    
    def __init__(self):
        """Initialize fresh product prioritizer."""
        self.freshness_boost = getattr(settings, 'freshness_boost_multiplier', 2.0)
        self.new_product_interval = getattr(
            settings, 'new_product_scan_interval_minutes', 1
        )
    
    async def boost_priority_for_fresh(
        self,
        base_priority: float,
        product: Product,
    ) -> float:
        """
        Boost priority score for fresh products.
        
        Args:
            base_priority: Base priority score
            product: Product to check
            
        Returns:
            Boosted priority score
        """
        if await new_product_detector.is_new_product(product):
            freshness_score = await new_product_detector.get_freshness_score(product)
            # Boost priority based on freshness
            boost = 1.0 + (freshness_score * (self.freshness_boost - 1.0))
            boosted_priority = base_priority * boost
            
            logger.debug(
                f"Boosted priority for fresh product {product.sku}: "
                f"{base_priority:.2f} -> {boosted_priority:.2f} "
                f"(freshness: {freshness_score:.2f})"
            )
            
            return boosted_priority
        
        return base_priority
    
    async def get_scan_interval(
        self,
        base_interval_minutes: int,
        product: Product,
    ) -> int:
        """
        Get adjusted scan interval for product based on freshness.
        
        Args:
            base_interval_minutes: Base scan interval in minutes
            product: Product to check
            
        Returns:
            Adjusted interval in minutes
        """
        if await new_product_detector.is_new_product(product):
            # Scan new products more frequently
            return min(self.new_product_interval, base_interval_minutes)
        
        return base_interval_minutes
    
    async def prioritize_products(
        self,
        products: List[Product],
        base_priorities: Optional[dict] = None,
    ) -> List[Product]:
        """
        Prioritize products by freshness, boosting fresh products.
        
        Args:
            products: List of products to prioritize
            base_priorities: Optional dict mapping product_id to base priority
            
        Returns:
            Sorted list (fresh products first)
        """
        if not base_priorities:
            base_priorities = {p.id: 5.0 for p in products}  # Default priority
        
        # Calculate boosted priorities
        scored_products = []
        for product in products:
            base_priority = base_priorities.get(product.id, 5.0)
            boosted_priority = await self.boost_priority_for_fresh(base_priority, product)
            scored_products.append((boosted_priority, product))
        
        # Sort by boosted priority (highest first)
        scored_products.sort(key=lambda x: x[0], reverse=True)
        
        return [product for _, product in scored_products]
    
    def is_new_arrivals_section(self, category_name: str, url: str) -> bool:
        """
        Detect if a category is a "new arrivals" section.
        
        Args:
            category_name: Category name
            url: Category URL
            
        Returns:
            True if appears to be new arrivals section
        """
        text = f"{category_name} {url}".lower()
        new_arrivals_keywords = [
            "new arrivals",
            "new products",
            "just added",
            "latest",
            "recently added",
            "new items",
        ]
        
        return any(keyword in text for keyword in new_arrivals_keywords)
    
    async def should_prioritize_category(
        self,
        category_name: str,
        category_url: str,
    ) -> bool:
        """
        Check if category should be prioritized for new product scanning.
        
        Args:
            category_name: Category name
            category_url: Category URL
            
        Returns:
            True if should prioritize
        """
        return self.is_new_arrivals_section(category_name, category_url)


# Global fresh product prioritizer instance
fresh_product_prioritizer = FreshProductPrioritizer()
