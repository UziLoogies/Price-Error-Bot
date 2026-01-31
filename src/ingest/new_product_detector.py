"""New product detection and prioritization.

Identifies and prioritizes newly listed products (<24 hours old)
as prime candidates for pricing errors.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Product
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class NewProductDetector:
    """
    Detects and prioritizes newly listed products.
    
    New products (<24 hours old) are prime candidates for pricing errors
    as they may have placeholder prices or typos that haven't been caught yet.
    """
    
    def __init__(self, hours_threshold: int = None):
        """
        Initialize new product detector.
        
        Args:
            hours_threshold: Hours threshold for "new" products (defaults to config)
        """
        self.hours_threshold = hours_threshold or getattr(
            settings, 'new_product_hours_threshold', 24
        )
    
    async def identify_new_products(
        self,
        store: str,
        hours_threshold: Optional[int] = None,
    ) -> List[Product]:
        """
        Identify products added in the last N hours.
        
        Args:
            store: Store identifier
            hours_threshold: Hours threshold (defaults to instance default)
            
        Returns:
            List of Product objects that are "new"
        """
        threshold = hours_threshold or self.hours_threshold
        cutoff_time = datetime.utcnow() - timedelta(hours=threshold)
        
        async with AsyncSessionLocal() as db:
            query = select(Product).where(
                Product.store == store,
                Product.created_at >= cutoff_time,
            ).order_by(Product.created_at.desc())
            
            result = await db.execute(query)
            products = result.scalars().all()
            
            logger.info(
                f"Found {len(products)} new products for {store} "
                f"(added in last {threshold} hours)"
            )
            
            return products
    
    async def is_new_product(
        self,
        product: Product,
        hours_threshold: Optional[int] = None,
    ) -> bool:
        """
        Check if a product is considered "new".
        
        Args:
            product: Product to check
            hours_threshold: Hours threshold (defaults to instance default)
            
        Returns:
            True if product is new
        """
        threshold = hours_threshold or self.hours_threshold
        
        # Use first_seen_at if available, otherwise created_at
        reference_time = getattr(product, 'first_seen_at', None) or product.created_at
        
        age_hours = (datetime.utcnow() - reference_time).total_seconds() / 3600
        return age_hours < threshold
    
    async def get_freshness_score(self, product: Product) -> float:
        """
        Calculate freshness score for a product.
        
        Higher score = newer product (more likely to have errors).
        Score ranges from 0.0 (old) to 1.0 (brand new).
        
        Args:
            product: Product to score
            
        Returns:
            Freshness score (0.0-1.0)
        """
        # Use first_seen_at if available, otherwise created_at
        reference_time = getattr(product, 'first_seen_at', None) or product.created_at
        
        age_hours = (datetime.utcnow() - reference_time).total_seconds() / 3600
        
        # Score decreases linearly with age
        # Products <1 hour old = 1.0
        # Products at threshold = 0.5
        # Products >threshold = 0.0
        if age_hours < 1:
            return 1.0
        elif age_hours >= self.hours_threshold:
            return 0.0
        else:
            # Linear decay from 1.0 to 0.5 over threshold hours
            return 1.0 - (age_hours / self.hours_threshold) * 0.5
    
    async def prioritize_new_products(
        self,
        products: List[Product],
    ) -> List[Product]:
        """
        Prioritize products by freshness (newest first).
        
        Args:
            products: List of products to prioritize
            
        Returns:
            Sorted list (newest first)
        """
        # Calculate freshness scores
        scored_products = []
        for product in products:
            score = await self.get_freshness_score(product)
            scored_products.append((score, product))
        
        # Sort by score (highest first)
        scored_products.sort(key=lambda x: x[0], reverse=True)
        
        return [product for _, product in scored_products]
    
    async def get_new_product_count(
        self,
        store: Optional[str] = None,
        hours_threshold: Optional[int] = None,
    ) -> int:
        """
        Get count of new products.
        
        Args:
            store: Optional store filter
            hours_threshold: Hours threshold
            
        Returns:
            Count of new products
        """
        threshold = hours_threshold or self.hours_threshold
        cutoff_time = datetime.utcnow() - timedelta(hours=threshold)
        
        async with AsyncSessionLocal() as db:
            query = select(Product).where(Product.created_at >= cutoff_time)
            
            if store:
                query = query.where(Product.store == store)
            
            result = await db.execute(select(func.count()).select_from(query.subquery()))
            count = result.scalar() or 0
            
            return count


# Global new product detector instance
new_product_detector = NewProductDetector()
