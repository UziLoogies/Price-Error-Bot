"""Price baseline calculation and tracking for anomaly detection.

Implements rolling average baseline calculation, price statistics,
and anomaly detection based on historical price data.
"""

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, PriceHistory

logger = logging.getLogger(__name__)


@dataclass
class PriceStatistics:
    """Statistical summary of price history for a product."""
    
    product_id: int
    count: int                          # Number of price observations
    mean: Decimal                       # Average price
    median: Decimal                     # Median price
    std_dev: float                      # Standard deviation
    min_price: Decimal                  # Minimum price seen
    max_price: Decimal                  # Maximum price seen
    price_range: Decimal                # max - min
    coefficient_of_variation: float     # std_dev / mean (price stability)
    
    @property
    def is_stable(self) -> bool:
        """Check if price is relatively stable (CV < 0.15)."""
        return self.coefficient_of_variation < 0.15


@dataclass
class ProductBaseline:
    """Baseline price information for a product."""
    
    product_id: int
    avg_price_7d: Optional[Decimal]     # 7-day rolling average
    avg_price_30d: Optional[Decimal]    # 30-day rolling average
    min_price_seen: Decimal             # All-time minimum
    max_price_seen: Decimal             # All-time maximum
    current_baseline: Decimal           # Best estimate of "normal" price
    price_stability: float              # 0.0-1.0 (1.0 = very stable)
    last_calculated: datetime
    observation_count: int
    last_price: Optional[Decimal]       # Most recent observed price
    
    def get_discount_from_baseline(self, current_price: Decimal) -> float:
        """Calculate discount percentage from baseline."""
        if self.current_baseline <= 0:
            return 0.0
        return float((1 - current_price / self.current_baseline) * 100)
    
    def is_below_minimum(self, price: Decimal) -> bool:
        """Check if price is below historical minimum."""
        return price < self.min_price_seen
    
    def get_percentile(self, price: Decimal, stats: PriceStatistics) -> float:
        """Estimate percentile of price in distribution (assuming normal)."""
        if stats.std_dev == 0:
            return 50.0
        z_score = float(price - stats.mean) / stats.std_dev
        # Approximate percentile from z-score
        # Using simplified approximation
        if z_score < -3:
            return 0.1
        elif z_score > 3:
            return 99.9
        else:
            # Linear approximation in middle range
            return max(0.1, min(99.9, 50 + z_score * 15))
    
    def get_seasonal_adjustment(self, current_date: datetime) -> float:
        """
        Get seasonal price adjustment factor.
        
        Prices may be lower during certain seasons (e.g., Black Friday, clearance).
        This helps adjust discount thresholds contextually.
        
        Args:
            current_date: Current date
            
        Returns:
            Adjustment factor (0.8-1.0, lower = allow deeper discounts)
        """
        month = current_date.month
        
        # Black Friday / Holiday season (Nov-Dec)
        if month in [11, 12]:
            return 0.85  # Allow deeper discounts
        
        # Post-holiday clearance (Jan)
        if month == 1:
            return 0.80  # Very deep discounts expected
        
        # Summer clearance (July-Aug)
        if month in [7, 8]:
            return 0.90  # Slight adjustment
        
        return 1.0  # Normal season


class BaselineCalculator:
    """
    Calculates and tracks price baselines for products.
    
    Uses price history to establish what "normal" pricing looks like,
    enabling detection of anomalous (potentially erroneous) prices.
    """
    
    def __init__(
        self,
        window_7d: int = 7,
        window_30d: int = 30,
        min_observations: int = 3,
    ):
        """
        Initialize baseline calculator.
        
        Args:
            window_7d: Days for short-term rolling average
            window_30d: Days for long-term rolling average
            min_observations: Minimum observations needed for reliable baseline
        """
        self.window_7d = window_7d
        self.window_30d = window_30d
        self.min_observations = min_observations
    
    async def get_price_history(
        self,
        db: AsyncSession,
        product_id: int,
        days: Optional[int] = None,
    ) -> List[PriceHistory]:
        """
        Get price history for a product.
        
        Args:
            db: Database session
            product_id: Product ID
            days: Limit to last N days (None = all history)
            
        Returns:
            List of PriceHistory records ordered by date
        """
        query = (
            select(PriceHistory)
            .where(PriceHistory.product_id == product_id)
            .order_by(PriceHistory.fetched_at.desc())
        )
        
        if days:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.where(PriceHistory.fetched_at >= cutoff)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    async def calculate_statistics(
        self,
        db: AsyncSession,
        product_id: int,
        days: Optional[int] = None,
    ) -> Optional[PriceStatistics]:
        """
        Calculate price statistics for a product.
        
        Args:
            db: Database session
            product_id: Product ID
            days: Limit to last N days
            
        Returns:
            PriceStatistics or None if insufficient data
        """
        history = await self.get_price_history(db, product_id, days)
        
        if len(history) < self.min_observations:
            return None
        
        prices = [float(h.price) for h in history if h.price > 0]
        
        if len(prices) < self.min_observations:
            return None
        
        mean = statistics.mean(prices)
        median = statistics.median(prices)
        std_dev = statistics.stdev(prices) if len(prices) > 1 else 0.0
        min_price = min(prices)
        max_price = max(prices)
        
        cv = std_dev / mean if mean > 0 else 0.0
        
        return PriceStatistics(
            product_id=product_id,
            count=len(prices),
            mean=Decimal(str(round(mean, 2))),
            median=Decimal(str(round(median, 2))),
            std_dev=std_dev,
            min_price=Decimal(str(round(min_price, 2))),
            max_price=Decimal(str(round(max_price, 2))),
            price_range=Decimal(str(round(max_price - min_price, 2))),
            coefficient_of_variation=cv,
        )
    
    async def calculate_baseline(
        self,
        db: AsyncSession,
        product_id: int,
    ) -> Optional[ProductBaseline]:
        """
        Calculate price baseline for a product.
        
        Args:
            db: Database session
            product_id: Product ID
            
        Returns:
            ProductBaseline or None if insufficient data
        """
        # Get all history for min/max and observation count
        all_history = await self.get_price_history(db, product_id)
        
        if not all_history:
            return None
        
        # Calculate rolling averages
        history_7d = await self.get_price_history(db, product_id, self.window_7d)
        history_30d = await self.get_price_history(db, product_id, self.window_30d)
        
        avg_7d = None
        avg_30d = None
        
        if history_7d:
            prices_7d = [float(h.price) for h in history_7d if h.price > 0]
            if prices_7d:
                avg_7d = Decimal(str(round(statistics.mean(prices_7d), 2)))
        
        if history_30d:
            prices_30d = [float(h.price) for h in history_30d if h.price > 0]
            if prices_30d:
                avg_30d = Decimal(str(round(statistics.mean(prices_30d), 2)))
        
        # Calculate overall statistics
        all_prices = [float(h.price) for h in all_history if h.price > 0]
        
        if not all_prices:
            return None
        
        min_price = Decimal(str(round(min(all_prices), 2)))
        max_price = Decimal(str(round(max(all_prices), 2)))
        
        # Calculate price stability (1 - normalized CV)
        mean = statistics.mean(all_prices)
        std_dev = statistics.stdev(all_prices) if len(all_prices) > 1 else 0.0
        cv = std_dev / mean if mean > 0 else 0.0
        stability = max(0.0, min(1.0, 1.0 - cv))
        
        # Determine current baseline (prefer 7d avg if stable, else 30d, else median)
        if avg_7d and stability > 0.7:
            current_baseline = avg_7d
        elif avg_30d:
            current_baseline = avg_30d
        else:
            current_baseline = Decimal(str(round(statistics.median(all_prices), 2)))
        
        return ProductBaseline(
            product_id=product_id,
            avg_price_7d=avg_7d,
            avg_price_30d=avg_30d,
            min_price_seen=min_price,
            max_price_seen=max_price,
            current_baseline=current_baseline,
            price_stability=stability,
            last_calculated=datetime.utcnow(),
            observation_count=len(all_history),
            last_price=all_history[0].price if all_history else None,
        )
    
    async def is_anomaly(
        self,
        db: AsyncSession,
        product_id: int,
        current_price: Decimal,
        z_threshold: float = 2.5,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a price is anomalous based on history.
        
        Args:
            db: Database session
            product_id: Product ID
            current_price: Current price to check
            z_threshold: Z-score threshold for anomaly detection
            
        Returns:
            Tuple of (is_anomaly, reason)
        """
        stats = await self.calculate_statistics(db, product_id)
        
        if not stats:
            return False, "Insufficient price history"
        
        baseline = await self.calculate_baseline(db, product_id)
        
        if not baseline:
            return False, "Could not calculate baseline"
        
        reasons = []
        
        # Check 1: Below historical minimum
        if current_price < baseline.min_price_seen:
            discount_from_min = float((1 - current_price / baseline.min_price_seen) * 100)
            reasons.append(f"Below historical minimum (${baseline.min_price_seen}) by {discount_from_min:.1f}%")
        
        # Check 2: Z-score based detection
        if stats.std_dev > 0:
            z_score = float(current_price - stats.mean) / stats.std_dev
            if z_score < -z_threshold:
                reasons.append(f"Z-score of {z_score:.2f} (threshold: -{z_threshold})")
        
        # Check 3: Significant discount from baseline
        discount_from_baseline = baseline.get_discount_from_baseline(current_price)
        if discount_from_baseline >= 50:
            reasons.append(f"{discount_from_baseline:.1f}% below baseline (${baseline.current_baseline})")
        
        is_anomaly = len(reasons) > 0
        reason = "; ".join(reasons) if reasons else None
        
        return is_anomaly, reason
    
    async def update_baseline(
        self,
        db: AsyncSession,
        product_id: int,
        new_price: Decimal,
        original_price: Optional[Decimal] = None,
    ) -> None:
        """
        Record a new price observation for baseline calculation.
        
        Args:
            db: Database session
            product_id: Product ID
            new_price: Observed price
            original_price: Strikethrough/was price if available
        """
        # Create new price history entry
        price_entry = PriceHistory(
            product_id=product_id,
            price=new_price,
            original_price=original_price,
            fetched_at=datetime.utcnow(),
        )
        db.add(price_entry)
        await db.commit()
        
        logger.debug(f"Recorded price ${new_price} for product {product_id}")
    
    async def get_baseline_for_sku(
        self,
        db: AsyncSession,
        store: str,
        sku: str,
    ) -> Optional[ProductBaseline]:
        """
        Get baseline for a product by store and SKU.
        
        Args:
            db: Database session
            store: Store identifier
            sku: Product SKU
            
        Returns:
            ProductBaseline or None
        """
        # Find product ID
        query = select(Product).where(Product.store == store, Product.sku == sku)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            return None
        
        return await self.calculate_baseline(db, product.id)
    
    async def get_or_create_product(
        self,
        db: AsyncSession,
        store: str,
        sku: str,
        url: Optional[str] = None,
        title: Optional[str] = None,
        msrp: Optional[Decimal] = None,
    ) -> Product:
        """
        Get or create a product record.
        
        Args:
            db: Database session
            store: Store identifier
            sku: Product SKU
            url: Product URL
            title: Product title
            msrp: MSRP if known
            
        Returns:
            Product model instance
        """
        query = select(Product).where(Product.store == store, Product.sku == sku)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if product:
            # Update fields if provided
            if url and not product.url:
                product.url = url
            if title and not product.title:
                product.title = title
            if msrp and not product.msrp:
                product.msrp = msrp
            await db.commit()
            return product
        
        # Create new product
        product = Product(
            store=store,
            sku=sku,
            url=url,
            title=title,
            msrp=msrp,
        )
        db.add(product)
        await db.commit()
        await db.refresh(product)
        
        return product
    
    async def record_price_observation(
        self,
        db: AsyncSession,
        store: str,
        sku: str,
        price: Decimal,
        original_price: Optional[Decimal] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
        msrp: Optional[Decimal] = None,
    ) -> tuple[Product, ProductBaseline]:
        """
        Record a price observation and return updated baseline.
        
        Args:
            db: Database session
            store: Store identifier
            sku: Product SKU
            price: Observed price
            original_price: Strikethrough price
            url: Product URL
            title: Product title
            msrp: MSRP
            
        Returns:
            Tuple of (Product, ProductBaseline)
        """
        product = await self.get_or_create_product(db, store, sku, url, title, msrp)
        await self.update_baseline(db, product.id, price, original_price)
        baseline = await self.calculate_baseline(db, product.id)
        
        return product, baseline
    
    def get_context_aware_discount_threshold(
        self,
        baseline: ProductBaseline,
        category: Optional[str] = None,
    ) -> float:
        """
        Get context-aware discount threshold based on historical price patterns.
        
        Args:
            baseline: Product baseline
            category: Optional category
            
        Returns:
            Discount threshold percentage (e.g., 40.0 = 40% off)
        """
        base_threshold = 40.0  # Default 40% off
        
        # Adjust based on price stability
        if baseline.price_stability > 0.8:
            # Very stable prices - lower threshold (smaller discounts are anomalies)
            base_threshold = 30.0
        elif baseline.price_stability < 0.5:
            # Volatile prices - higher threshold (need bigger discount to be significant)
            base_threshold = 50.0
        
        # Adjust based on category (electronics vs apparel)
        if category:
            category_lower = category.lower()
            if "electronics" in category_lower or "computer" in category_lower:
                # Electronics: stricter threshold
                base_threshold = min(base_threshold, 35.0)
            elif "apparel" in category_lower or "clothing" in category_lower:
                # Apparel: more lenient (sales are common)
                base_threshold = max(base_threshold, 50.0)
        
        # Apply seasonal adjustment
        seasonal_factor = baseline.get_seasonal_adjustment(datetime.utcnow())
        adjusted_threshold = base_threshold * seasonal_factor
        
        return adjusted_threshold


# Global baseline calculator instance
baseline_calculator = BaselineCalculator()
