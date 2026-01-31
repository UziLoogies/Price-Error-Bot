"""Scheduled baseline aggregation job.

Periodically aggregates PriceHistory into ProductBaselineCache,
calculates statistics, and prunes old data.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
import statistics
from typing import List, Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, PriceHistory, ProductBaselineCache
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class BaselineAggregationJob:
    """
    Scheduled job that aggregates price history into cached baselines.
    
    Runs periodically to:
    1. Calculate rolling averages and statistics for all products
    2. Update ProductBaselineCache table
    3. Prune old price history data
    """
    
    def __init__(
        self,
        retention_days: int = 90,
        batch_size: int = 100,
    ):
        """
        Initialize baseline aggregation job.
        
        Args:
            retention_days: Days of price history to retain
            batch_size: Products to process per batch
        """
        self.retention_days = retention_days
        self.batch_size = batch_size
    
    async def run(self) -> dict:
        """
        Run the baseline aggregation job.
        
        Returns:
            Dict with job statistics
        """
        logger.info("Starting baseline aggregation job")
        start_time = datetime.utcnow()
        
        stats = {
            "products_processed": 0,
            "baselines_updated": 0,
            "baselines_created": 0,
            "history_pruned": 0,
            "errors": 0,
        }
        
        async with AsyncSessionLocal() as db:
            # Get all products with price history
            products = await self._get_products_with_history(db)
            
            logger.info(f"Found {len(products)} products with price history")
            
            # Process in batches
            for i in range(0, len(products), self.batch_size):
                batch = products[i:i + self.batch_size]
                batch_stats = await self._process_batch(db, batch)
                
                stats["products_processed"] += batch_stats["processed"]
                stats["baselines_updated"] += batch_stats["updated"]
                stats["baselines_created"] += batch_stats["created"]
                stats["errors"] += batch_stats["errors"]
            
            # Prune old history
            stats["history_pruned"] = await self._prune_old_history(db)
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Baseline aggregation complete in {duration:.1f}s: "
            f"{stats['products_processed']} products, "
            f"{stats['baselines_updated']} updated, "
            f"{stats['baselines_created']} created, "
            f"{stats['history_pruned']} history records pruned"
        )
        
        return stats
    
    async def _get_products_with_history(self, db: AsyncSession) -> List[Product]:
        """Get all products that have price history."""
        query = (
            select(Product)
            .join(PriceHistory)
            .distinct()
        )
        result = await db.execute(query)
        return list(result.scalars().all())
    
    async def _process_batch(
        self,
        db: AsyncSession,
        products: List[Product],
    ) -> dict:
        """Process a batch of products."""
        stats = {"processed": 0, "updated": 0, "created": 0, "errors": 0}
        
        for product in products:
            try:
                result = await self._update_baseline_cache(db, product)
                stats["processed"] += 1
                
                if result is True:
                    stats["created"] += 1
                elif result is False:
                    stats["updated"] += 1
                # If result is None, it's a no-op, don't increment created/updated
                    
            except Exception as e:
                logger.error(f"Error processing product {product.id}: {e}")
                stats["errors"] += 1
        
        await db.commit()
        return stats
    
    async def _update_baseline_cache(
        self,
        db: AsyncSession,
        product: Product,
    ) -> Optional[bool]:
        """
        Update or create baseline cache for a product.
        
        Args:
            db: Database session
            product: Product to update baseline cache for
            
        Returns:
            True if a new ProductBaselineCache was created, False if an existing one was updated, None if no-op
        """
        # Get price history
        now = datetime.utcnow()
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)
        
        # Get all history
        history_query = (
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .order_by(PriceHistory.fetched_at.desc())
        )
        result = await db.execute(history_query)
        all_history = list(result.scalars().all())
        
        if not all_history:
            # Return None since we didn't create or update anything (no-op)
            return None
        
        # Calculate statistics
        all_prices = [float(h.price) for h in all_history if h.price > 0]
        prices_7d = [float(h.price) for h in all_history if h.price > 0 and h.fetched_at >= cutoff_7d]
        prices_30d = [float(h.price) for h in all_history if h.price > 0 and h.fetched_at >= cutoff_30d]
        
        if not all_prices:
            # Return None since we didn't create or update anything (no-op)
            return None
        
        avg_7d = Decimal(str(round(statistics.mean(prices_7d), 2))) if prices_7d else None
        avg_30d = Decimal(str(round(statistics.mean(prices_30d), 2))) if prices_30d else None
        
        min_price = Decimal(str(round(min(all_prices), 2)))
        max_price = Decimal(str(round(max(all_prices), 2)))
        
        mean = statistics.mean(all_prices)
        std_dev = statistics.stdev(all_prices) if len(all_prices) > 1 else 0.0
        cv = std_dev / mean if mean > 0 else 0.0
        stability = max(0.0, min(1.0, 1.0 - cv))
        
        # Determine current baseline
        if avg_7d and stability > 0.7:
            current_baseline = avg_7d
        elif avg_30d:
            current_baseline = avg_30d
        else:
            current_baseline = Decimal(str(round(statistics.median(all_prices), 2)))
        
        # Get or create cache entry
        cache_query = select(ProductBaselineCache).where(
            ProductBaselineCache.product_id == product.id
        )
        cache_result = await db.execute(cache_query)
        cache = cache_result.scalar_one_or_none()
        
        if cache:
            # Update existing
            cache.avg_price_7d = avg_7d
            cache.avg_price_30d = avg_30d
            cache.min_price_seen = min_price
            cache.max_price_seen = max_price
            cache.current_baseline = current_baseline
            cache.price_stability = stability
            cache.std_deviation = std_dev if std_dev > 0 else None
            cache.observation_count = len(all_history)
            cache.last_calculated = now
            cache.last_price = all_history[0].price
            cache.last_price_at = all_history[0].fetched_at
            return False  # Updated existing
        else:
            # Create new
            cache = ProductBaselineCache(
                product_id=product.id,
                avg_price_7d=avg_7d,
                avg_price_30d=avg_30d,
                min_price_seen=min_price,
                max_price_seen=max_price,
                current_baseline=current_baseline,
                price_stability=stability,
                std_deviation=std_dev if std_dev > 0 else None,
                observation_count=len(all_history),
                last_calculated=now,
                last_price=all_history[0].price,
                last_price_at=all_history[0].fetched_at,
            )
            db.add(cache)
            return True  # Created new
    
    async def _prune_old_history(self, db: AsyncSession) -> int:
        """Prune price history older than retention period."""
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        
        # Count before delete
        count_query = (
            select(func.count())
            .select_from(PriceHistory)
            .where(PriceHistory.fetched_at < cutoff)
        )
        result = await db.execute(count_query)
        count = result.scalar() or 0
        
        if count > 0:
            delete_query = delete(PriceHistory).where(PriceHistory.fetched_at < cutoff)
            await db.execute(delete_query)
            await db.commit()
            logger.info(f"Pruned {count} price history records older than {self.retention_days} days")
        
        return count


# Global job instance
baseline_job = BaselineAggregationJob()


async def run_baseline_aggregation() -> dict:
    """Entry point for scheduler to run baseline aggregation."""
    return await baseline_job.run()
