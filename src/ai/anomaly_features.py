"""Feature engineering for anomaly detection."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PriceHistory, Product

logger = logging.getLogger(__name__)


class AnomalyFeatureExtractor:
    """
    Extract features for anomaly detection.
    
    Features include:
    - Historical price trends (moving averages, volatility)
    - Competitor price features (if available)
    - Category-based features
    - Temporal features (day of week, seasonality)
    - Price change velocity
    - Statistical features (z-scores, percentiles)
    """
    
    async def extract_features(
        self,
        product_id: int,
        current_price: Decimal,
        db: AsyncSession,
    ) -> Dict[str, float]:
        """
        Extract all features for a product and price.
        
        Args:
            product_id: Product ID
            current_price: Current price to evaluate
            db: Database session
            
        Returns:
            Dictionary of feature names to values
        """
        features = {}
        
        # Get product
        product = await db.get(Product, product_id)
        if not product:
            return features
        
        # Historical trend features
        trend_features = await self.get_historical_trends(product_id, db, days=30)
        features.update(trend_features)
        
        # Price change velocity
        velocity_features = await self.get_price_velocity(product_id, db)
        features.update(velocity_features)
        
        # Statistical features
        stats_features = await self.get_statistical_features(
            product_id,
            current_price,
            db,
        )
        features.update(stats_features)
        
        # Temporal features
        temporal_features = self.get_temporal_features()
        features.update(temporal_features)
        
        # Category features (if available)
        if product.title:
            category_features = self.get_category_features(product.title)
            features.update(category_features)
        
        return features
    
    async def get_historical_trends(
        self,
        product_id: int,
        db: AsyncSession,
        days: int = 30,
    ) -> Dict[str, float]:
        """
        Get historical price trend features.
        
        Args:
            product_id: Product ID
            db: Database session
            days: Number of days to look back
            
        Returns:
            Dictionary of trend features
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = select(PriceHistory).where(
            PriceHistory.product_id == product_id,
            PriceHistory.fetched_at >= cutoff_date,
        ).order_by(PriceHistory.fetched_at.asc())
        
        result = await db.execute(query)
        history = result.scalars().all()
        
        if not history:
            return {
                "has_history": 0.0,
                "price_count": 0.0,
                "avg_price": 0.0,
                "price_volatility": 0.0,
                "trend_slope": 0.0,
            }
        
        prices = [float(h.price) for h in history]
        
        # Basic statistics
        avg_price = float(np.mean(prices))
        std_price = float(np.std(prices)) if len(prices) > 1 else 0.0
        volatility = std_price / avg_price if avg_price > 0 else 0.0
        
        # Trend slope (linear regression)
        trend_slope = 0.0
        if len(prices) >= 2:
            x = np.arange(len(prices))
            trend_slope = float(np.polyfit(x, prices, 1)[0])  # Linear fit slope
        
        # Moving averages
        ma_7 = float(np.mean(prices[-7:])) if len(prices) >= 7 else avg_price
        ma_14 = float(np.mean(prices[-14:])) if len(prices) >= 14 else avg_price
        
        return {
            "has_history": 1.0,
            "price_count": float(len(prices)),
            "avg_price": avg_price,
            "std_price": std_price,
            "price_volatility": volatility,
            "trend_slope": trend_slope,
            "ma_7": ma_7,
            "ma_14": ma_14,
            "min_price": float(np.min(prices)),
            "max_price": float(np.max(prices)),
            "price_range": float(np.max(prices) - np.min(prices)),
        }
    
    async def get_price_velocity(
        self,
        product_id: int,
        db: AsyncSession,
        hours: int = 24,
    ) -> Dict[str, float]:
        """
        Get price change velocity features.
        
        Args:
            product_id: Product ID
            db: Database session
            hours: Hours to look back
            
        Returns:
            Dictionary of velocity features
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        query = select(PriceHistory).where(
            PriceHistory.product_id == product_id,
            PriceHistory.fetched_at >= cutoff_time,
        ).order_by(PriceHistory.fetched_at.asc())
        
        result = await db.execute(query)
        recent_history = result.scalars().all()
        
        if len(recent_history) < 2:
            return {
                "price_changes_24h": 0.0,
                "price_change_rate": 0.0,
                "max_change_24h": 0.0,
            }
        
        prices = [float(h.price) for h in recent_history]
        changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        
        change_count = len([c for c in changes if c > 0.01])  # Ignore tiny changes
        max_change = max(changes) if changes else 0.0
        avg_change = np.mean(changes) if changes else 0.0
        
        # Change rate (changes per hour)
        time_span_hours = (recent_history[-1].fetched_at - recent_history[0].fetched_at).total_seconds() / 3600
        change_rate = change_count / max(time_span_hours, 0.1) if time_span_hours > 0 else 0.0
        
        return {
            "price_changes_24h": float(change_count),
            "price_change_rate": change_rate,
            "max_change_24h": max_change,
            "avg_change_24h": float(avg_change),
        }
    
    async def get_statistical_features(
        self,
        product_id: int,
        current_price: Decimal,
        db: AsyncSession,
    ) -> Dict[str, float]:
        """
        Get statistical features (z-scores, percentiles).
        
        Args:
            product_id: Product ID
            current_price: Current price
            db: Database session
            
        Returns:
            Dictionary of statistical features
        """
        # Get all historical prices
        query = select(PriceHistory.price).where(
            PriceHistory.product_id == product_id
        ).order_by(PriceHistory.fetched_at.desc()).limit(100)
        
        result = await db.execute(query)
        prices = [float(row[0]) for row in result.fetchall()]
        
        if not prices:
            return {
                "z_score": 0.0,
                "percentile": 0.5,
                "price_deviation": 0.0,
            }
        
        prices_array = np.array(prices)
        current_price_float = float(current_price)
        
        # Z-score
        mean_price = np.mean(prices_array)
        std_price = np.std(prices_array) if len(prices_array) > 1 else 1.0
        z_score = (current_price_float - mean_price) / max(std_price, 0.01)
        
        # Percentile
        percentile = float(np.sum(prices_array <= current_price_float) / len(prices_array))
        
        # Deviation from mean
        price_deviation = (current_price_float - mean_price) / max(mean_price, 0.01)
        
        return {
            "z_score": float(z_score),
            "percentile": percentile,
            "price_deviation": float(price_deviation),
            "mean_price": float(mean_price),
            "std_price": float(std_price),
        }
    
    def get_temporal_features(self) -> Dict[str, float]:
        """
        Get temporal features (day of week, hour, etc.).
        
        Returns:
            Dictionary of temporal features
        """
        now = datetime.utcnow()
        
        # Day of week (0 = Monday, 6 = Sunday)
        day_of_week = now.weekday()
        
        # Hour of day
        hour = now.hour
        
        # Is weekend
        is_weekend = 1.0 if day_of_week >= 5 else 0.0
        
        # Is business hours (9 AM - 5 PM)
        is_business_hours = 1.0 if 9 <= hour <= 17 else 0.0
        
        # Month (for seasonality)
        month = now.month
        
        return {
            "day_of_week": float(day_of_week),
            "hour": float(hour),
            "is_weekend": is_weekend,
            "is_business_hours": is_business_hours,
            "month": float(month),
        }
    
    def get_category_features(self, title: str) -> Dict[str, float]:
        """
        Get category-based features from product title.
        
        Args:
            title: Product title
            
        Returns:
            Dictionary of category features
        """
        if not title:
            return {}
        
        title_lower = title.lower()
        
        # Category indicators
        is_electronics = 1.0 if any(word in title_lower for word in [
            "tv", "television", "monitor", "laptop", "computer", "phone", "tablet",
            "headphones", "speaker", "camera"
        ]) else 0.0
        
        is_apparel = 1.0 if any(word in title_lower for word in [
            "shirt", "pants", "shoes", "jacket", "dress", "sweater"
        ]) else 0.0
        
        is_home = 1.0 if any(word in title_lower for word in [
            "furniture", "chair", "table", "sofa", "bed", "lamp"
        ]) else 0.0
        
        return {
            "is_electronics": is_electronics,
            "is_apparel": is_apparel,
            "is_home": is_home,
        }


# Global feature extractor instance
anomaly_feature_extractor = AnomalyFeatureExtractor()
