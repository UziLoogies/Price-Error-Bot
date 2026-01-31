"""Comparative pricing engine for cross-site price comparison.

Compares prices across multiple sites for the same SKU to identify
anomalous prices that deviate significantly from market average.
"""

import logging
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Product, PriceHistory
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass
class PriceComparison:
    """Result of price comparison."""
    current_price: Decimal
    market_average: Optional[Decimal]
    market_min: Optional[Decimal]
    market_max: Optional[Decimal]
    deviation_percent: Optional[float]  # How much below/above average
    z_score: Optional[float]  # Standard deviations from mean
    is_anomalous: bool
    confidence: float  # 0.0-1.0
    sample_size: int  # Number of price points used


class ComparativePricingEngine:
    """
    Compares prices across sites and calculates market averages.
    
    Features:
    - Compare prices across multiple sites for same SKU
    - Calculate price deviation from market average
    - Flag prices >3 standard deviations below average
    - Use external APIs for reference prices
    - Cross-site price validation
    """
    
    def __init__(self):
        """Initialize comparative pricing engine."""
        self.market_window_days = getattr(settings, 'market_average_window_days', 30)
        self.sigma_threshold = getattr(settings, 'anomaly_sigma_threshold', 3.0)
        self.enabled = getattr(settings, 'comparative_pricing_enabled', True)
    
    async def get_market_average(
        self,
        sku: str,
        category: Optional[str] = None,
    ) -> Optional[Decimal]:
        """
        Get market average price for a SKU across all stores.
        
        Args:
            sku: Product SKU/identifier
            category: Optional category filter
            
        Returns:
            Market average price or None if insufficient data
        """
        if not self.enabled:
            return None
        
        cutoff_date = datetime.utcnow() - timedelta(days=self.market_window_days)
        
        async with AsyncSessionLocal() as db:
            # Get all products with this SKU across stores
            query = select(Product).where(Product.sku == sku)
            if category:
                # Note: Would need category field on Product or join
                pass
            
            result = await db.execute(query)
            products = result.scalars().all()
            
            if not products:
                return None
            
            # Get recent prices for all products with this SKU
            product_ids = [p.id for p in products]
            
            price_query = select(PriceHistory.price).where(
                PriceHistory.product_id.in_(product_ids),
                PriceHistory.fetched_at >= cutoff_date,
            ).order_by(PriceHistory.fetched_at.desc())
            
            price_result = await db.execute(price_query)
            prices = [row[0] for row in price_result.all() if row[0] is not None]
            
            if len(prices) < 3:
                return None  # Need at least 3 data points
            
            # Calculate average
            avg_price = sum(prices, Decimal(0)) / len(prices)
            return avg_price
    
    async def compare_price(
        self,
        price: Decimal,
        sku: str,
        category: Optional[str] = None,
    ) -> PriceComparison:
        """
        Compare a price against market average.
        
        Args:
            price: Current price to compare
            sku: Product SKU
            category: Optional category
            
        Returns:
            PriceComparison with analysis results
        """
        if not self.enabled:
            return PriceComparison(
                current_price=price,
                market_average=None,
                market_min=None,
                market_max=None,
                deviation_percent=None,
                z_score=None,
                is_anomalous=False,
                confidence=0.0,
                sample_size=0,
            )
        
        cutoff_date = datetime.utcnow() - timedelta(days=self.market_window_days)
        
        async with AsyncSessionLocal() as db:
            # Get all products with this SKU
            query = select(Product).where(Product.sku == sku)
            result = await db.execute(query)
            products = result.scalars().all()
            
            if not products:
                return PriceComparison(
                    current_price=price,
                    market_average=None,
                    market_min=None,
                    market_max=None,
                    deviation_percent=None,
                    z_score=None,
                    is_anomalous=False,
                    confidence=0.0,
                    sample_size=0,
                )
            
            # Get recent prices
            product_ids = [p.id for p in products]
            price_query = select(PriceHistory.price).where(
                PriceHistory.product_id.in_(product_ids),
                PriceHistory.fetched_at >= cutoff_date,
            )
            
            price_result = await db.execute(price_query)
            prices = [row[0] for row in price_result.all() if row[0] is not None]
            
            if len(prices) < 3:
                return PriceComparison(
                    current_price=price,
                    market_average=None,
                    market_min=None,
                    market_max=None,
                    deviation_percent=None,
                    z_score=None,
                    is_anomalous=False,
                    confidence=0.0,
                    sample_size=len(prices),
                )
            
            # Calculate statistics
            market_avg = sum(prices, Decimal(0)) / len(prices)
            market_min = min(prices)
            market_max = max(prices)
            
            # Calculate deviation
            if market_avg > 0:
                deviation_percent = float((market_avg - price) / market_avg * 100)
            else:
                deviation_percent = 0.0
            
            # Calculate Z-score
            if len(prices) >= 10:
                # Calculate standard deviation
                price_floats = [float(p) for p in prices]
                std_dev = statistics.stdev(price_floats)
                if std_dev > 0:
                    z_score = float((float(price) - float(market_avg)) / std_dev)
                else:
                    z_score = 0.0
            else:
                # Not enough data for reliable Z-score
                z_score = None
            
            # Determine if anomalous
            is_anomalous = False
            confidence = 0.0
            
            if z_score is not None:
                # Price is significantly below average
                if z_score < -self.sigma_threshold:
                    is_anomalous = True
                    confidence = min(1.0, abs(z_score) / self.sigma_threshold)
            elif deviation_percent > 50:  # More than 50% below average
                is_anomalous = True
                confidence = min(1.0, deviation_percent / 100)
            
            return PriceComparison(
                current_price=price,
                market_average=market_avg,
                market_min=market_min,
                market_max=market_max,
                deviation_percent=deviation_percent,
                z_score=z_score,
                is_anomalous=is_anomalous,
                confidence=confidence,
                sample_size=len(prices),
            )
    
    async def calculate_deviation(
        self,
        price: Decimal,
        market_avg: Decimal,
    ) -> float:
        """
        Calculate price deviation from market average as percentage.
        
        Args:
            price: Current price
            market_avg: Market average price
            
        Returns:
            Deviation percentage (positive = above average, negative = below)
        """
        if market_avg == 0:
            return 0.0
        
        deviation = float((price - market_avg) / market_avg * 100)
        return deviation
    
    async def is_anomalous_price(
        self,
        price: Decimal,
        sku: str,
        threshold_sigma: Optional[float] = None,
        category: Optional[str] = None,
    ) -> bool:
        """
        Check if price is anomalously low compared to market.
        
        Args:
            price: Price to check
            sku: Product SKU
            threshold_sigma: Sigma threshold (defaults to config)
            category: Optional category
            
        Returns:
            True if price is anomalous
        """
        if not self.enabled:
            return False
        
        threshold = threshold_sigma or self.sigma_threshold
        
        comparison = await self.compare_price(price, sku, category)
        
        if comparison.z_score is not None:
            return comparison.z_score < -threshold
        
        # Fallback to deviation percentage
        if comparison.deviation_percent is not None:
            return comparison.deviation_percent > 50.0  # >50% below average
        
        return False
    
    async def get_category_average(
        self,
        category: str,
        store: Optional[str] = None,
    ) -> Optional[Decimal]:
        """
        Get average price for a category (for category outlier detection).
        
        Args:
            category: Category name
            store: Optional store filter
            
        Returns:
            Average price for category or None
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.market_window_days)
        
        async with AsyncSessionLocal() as db:
            # This would require a category field on Product or a join
            # For now, return None (can be enhanced later)
            return None


# Global comparative pricing engine instance
comparative_pricing_engine = ComparativePricingEngine()
