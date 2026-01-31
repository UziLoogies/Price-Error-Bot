"""Rapid price change detector for decimal errors and large drops.

Tracks price change velocity and detects unusually large single-step
price drops that may indicate pricing errors.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Product, PriceHistory
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass
class RapidDropAlert:
    """Alert for rapid price drop."""
    product_id: int
    old_price: Decimal
    new_price: Decimal
    drop_percent: float
    is_decimal_error: bool
    change_velocity: float  # Changes per hour
    confidence: float


class RapidChangeDetector:
    """
    Detects rapid price changes that may indicate errors.
    
    Features:
    - Track price change velocity (price changes per hour)
    - Flag unusually large single-step price drops
    - Monitor products with frequent repricing
    - Detect decimal point errors (e.g., $500 → $50)
    - Alert on rapid changes for high-value items
    """
    
    def __init__(self):
        """Initialize rapid change detector."""
        self.enabled = getattr(settings, 'rapid_change_enabled', True)
        self.rapid_drop_threshold = getattr(settings, 'rapid_drop_threshold_percent', 50.0)
        self.decimal_error_detection = getattr(settings, 'decimal_error_detection', True)
        self.velocity_window_hours = 24
    
    async def track_price_change(
        self,
        product_id: int,
        old_price: Decimal,
        new_price: Decimal,
    ) -> None:
        """
        Track a price change for velocity calculation.
        
        Args:
            product_id: Product ID
            old_price: Previous price
            new_price: New price
        """
        if not self.enabled or old_price == new_price:
            return
        
        # Update price change count in database
        async with AsyncSessionLocal() as db:
            product = await db.get(Product, product_id)
            if product:
                # Increment change count
                if not hasattr(product, 'price_change_count_24h'):
                    # Would need migration to add this field
                    pass
                else:
                    product.price_change_count_24h = (product.price_change_count_24h or 0) + 1
                    product.last_price_change_at = datetime.utcnow()
                    await db.commit()
    
    async def detect_rapid_drop(
        self,
        product_id: int,
        new_price: Decimal,
    ) -> Optional[RapidDropAlert]:
        """
        Detect if a price drop is rapid/anomalous.
        
        Args:
            product_id: Product ID
            new_price: New price
            
        Returns:
            RapidDropAlert if detected, None otherwise
        """
        if not self.enabled:
            return None
        
        async with AsyncSessionLocal() as db:
            # Get recent price history
            cutoff = datetime.utcnow() - timedelta(hours=self.velocity_window_hours)
            
            query = select(PriceHistory).where(
                PriceHistory.product_id == product_id,
                PriceHistory.fetched_at >= cutoff,
            ).order_by(PriceHistory.fetched_at.desc()).limit(10)
            
            result = await db.execute(query)
            history = result.scalars().all()
            
            if len(history) < 2:
                return None  # Need at least 2 price points
            
            # Get previous price
            old_price = history[0].price if history else None
            if not old_price or old_price == new_price:
                return None
            
            # Calculate drop percentage
            if old_price > 0:
                drop_percent = float((old_price - new_price) / old_price * 100)
            else:
                return None
            
            # Check if drop exceeds threshold
            if drop_percent < self.rapid_drop_threshold:
                return None
            
            # Check for decimal error
            is_decimal_error = False
            if self.decimal_error_detection:
                is_decimal_error = self._is_decimal_error(old_price, new_price)
            
            # Calculate change velocity
            change_velocity = await self.get_change_velocity(product_id)
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                drop_percent,
                is_decimal_error,
                change_velocity,
            )
            
            return RapidDropAlert(
                product_id=product_id,
                old_price=old_price,
                new_price=new_price,
                drop_percent=drop_percent,
                is_decimal_error=is_decimal_error,
                change_velocity=change_velocity,
                confidence=confidence,
            )
    
    def _is_decimal_error(
        self,
        old_price: Decimal,
        new_price: Decimal,
    ) -> bool:
        """
        Detect if price change looks like a decimal point error.
        
        Examples:
        - $500.00 → $50.00 (decimal moved left)
        - $19.99 → $1.99 (decimal moved left)
        - $50.00 → $5.00 (decimal moved left)
        
        Args:
            old_price: Previous price
            new_price: New price
            
        Returns:
            True if appears to be decimal error
        """
        if old_price <= 0 or new_price <= 0:
            return False
        
        # Check if new price is approximately 1/10th of old price
        ratio = float(new_price / old_price)
        
        # Decimal moved left: new ≈ old / 10
        if 0.09 <= ratio <= 0.11:
            return True
        
        # Check if new price is exactly 1/100th (two decimal places)
        if 0.009 <= ratio <= 0.011:
            return True
        
        # Check if digits match (e.g., 500 → 50, 1999 → 199)
        old_str = str(old_price).replace(".", "").replace("$", "").strip()
        new_str = str(new_price).replace(".", "").replace("$", "").strip()
        
        # If new is old with last digit removed, might be decimal error
        if len(old_str) > 1 and new_str == old_str[:-1]:
            return True
        
        return False
    
    async def get_change_velocity(self, product_id: int) -> float:
        """
        Get price change velocity (changes per hour) for a product.
        
        Args:
            product_id: Product ID
            
        Returns:
            Changes per hour
        """
        async with AsyncSessionLocal() as db:
            cutoff = datetime.utcnow() - timedelta(hours=self.velocity_window_hours)
            
            query = select(func.count(PriceHistory.id)).where(
                PriceHistory.product_id == product_id,
                PriceHistory.fetched_at >= cutoff,
            )
            
            result = await db.execute(query)
            change_count = result.scalar() or 0
            
            return change_count / self.velocity_window_hours
    
    def _calculate_confidence(
        self,
        drop_percent: float,
        is_decimal_error: bool,
        change_velocity: float,
    ) -> float:
        """
        Calculate confidence in rapid drop detection.
        
        Args:
            drop_percent: Percentage drop
            is_decimal_error: Whether appears to be decimal error
            change_velocity: Changes per hour
            
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.5
        
        # Large drops = higher confidence
        if drop_percent >= 90:
            confidence += 0.3
        elif drop_percent >= 70:
            confidence += 0.2
        elif drop_percent >= 50:
            confidence += 0.1
        
        # Decimal errors = very high confidence
        if is_decimal_error:
            confidence += 0.2
        
        # Low velocity = higher confidence (unexpected change)
        if change_velocity < 1.0:
            confidence += 0.1
        
        return min(1.0, confidence)


# Global rapid change detector instance
rapid_change_detector = RapidChangeDetector()
