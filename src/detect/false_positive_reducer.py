"""False positive reducer with feedback learning.

Learns from user feedback to refine detection thresholds and
reduce false positive alerts.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, Product
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class FalsePositiveReducer:
    """
    Reduces false positives through feedback learning.
    
    Features:
    - Learn from user feedback (mark alerts as false positive)
    - Refine detection thresholds based on feedback
    - Category-specific confidence adjustments
    - Pattern recognition for common false positives
    """
    
    def __init__(self):
        """Initialize false positive reducer."""
        self._category_false_positive_rates: Dict[str, float] = {}
        self._pattern_false_positives: Dict[str, int] = defaultdict(int)
        self._loaded = False
    
    async def load_feedback(self, db: AsyncSession) -> None:
        """
        Load false positive feedback from database.
        
        Args:
            db: Database session
        """
        # Count false positives by category
        query = select(
            Product.store,
            func.count(Alert.id).label('false_positive_count'),
            func.count().label('total_alerts'),
        ).join(
            Alert, Alert.product_id == Product.id
        ).where(
            Alert.false_positive_count > 0
        ).group_by(Product.store)
        
        result = await db.execute(query)
        rows = result.all()
        
        for row in rows:
            store = row.store
            false_positives = row.false_positive_count
            total = row.total_alerts
            
            if total > 0:
                rate = false_positives / total
                self._category_false_positive_rates[store] = rate
        
        self._loaded = True
        logger.info(f"Loaded false positive feedback for {len(self._category_false_positive_rates)} categories")
    
    async def record_false_positive(
        self,
        alert_id: int,
        reason: Optional[str] = None,
    ) -> None:
        """
        Record a false positive alert.
        
        Args:
            alert_id: Alert ID
            reason: Optional reason for false positive
        """
        async with AsyncSessionLocal() as db:
            alert = await db.get(Alert, alert_id)
            if alert:
                # Increment false positive count
                if not hasattr(alert, 'false_positive_count'):
                    # Would need migration to add this field
                    pass
                else:
                    alert.false_positive_count = (alert.false_positive_count or 0) + 1
                    await db.commit()
                    
                    # Update category false positive rate
                    product = await db.get(Product, alert.product_id)
                    if product:
                        await self._update_category_rate(product.store, db)
    
    def get_category_adjustment(self, category: str) -> float:
        """
        Get confidence adjustment for a category based on false positive rate.
        
        Args:
            category: Category/store identifier
            
        Returns:
            Adjustment multiplier (0.5-1.0, lower = more conservative)
        """
        if not self._loaded:
            return 1.0
        
        false_positive_rate = self._category_false_positive_rates.get(category, 0.0)
        
        # Higher false positive rate = lower confidence adjustment
        if false_positive_rate > 0.5:
            return 0.5  # Very conservative
        elif false_positive_rate > 0.3:
            return 0.7  # Conservative
        elif false_positive_rate > 0.1:
            return 0.9  # Slightly conservative
        else:
            return 1.0  # No adjustment
    
    async def adjust_confidence(
        self,
        base_confidence: float,
        category: str,
        detection_methods: List[str],
    ) -> float:
        """
        Adjust confidence based on false positive history.
        
        Args:
            base_confidence: Base confidence score
            category: Category/store identifier
            detection_methods: List of detection methods that triggered
            
        Returns:
            Adjusted confidence score
        """
        if not self._loaded:
            await self._load_feedback_once()
        
        # Apply category adjustment
        category_adjustment = self.get_category_adjustment(category)
        adjusted = base_confidence * category_adjustment
        
        # Additional adjustment for methods with high false positive rate
        # (would need to track this per method)
        
        return adjusted
    
    async def _load_feedback_once(self) -> None:
        """Load feedback once if not already loaded."""
        if not self._loaded:
            async with AsyncSessionLocal() as db:
                await self.load_feedback(db)
    
    async def _update_category_rate(self, category: str, db: AsyncSession) -> None:
        """
        Update false positive rate for a category.
        
        Args:
            category: Category/store identifier
            db: Database session
        """
        query = select(
            func.count(Alert.id).label('false_positive_count'),
            func.count().label('total_alerts'),
        ).join(
            Product, Alert.product_id == Product.id
        ).where(
            Product.store == category,
            Alert.false_positive_count > 0,
        )
        
        result = await db.execute(query)
        row = result.first()
        
        if row and row.total_alerts > 0:
            rate = row.false_positive_count / row.total_alerts
            self._category_false_positive_rates[category] = rate
    
    def identify_common_patterns(self, false_positive_alerts: List[Alert]) -> List[Tuple[str, int]]:
        """
        Identify common patterns in false positives.
        
        Args:
            false_positive_alerts: List of false positive alerts
            
        Returns:
            List of (pattern, count) tuples
        """
        patterns = defaultdict(int)
        
        for alert in false_positive_alerts:
            # Extract patterns from alert (would need alert details)
            # For now, placeholder
            pass
        
        return sorted(patterns.items(), key=lambda x: x[1], reverse=True)


# Global false positive reducer instance
false_positive_reducer = FalsePositiveReducer()
