"""Machine learning model training for anomaly detection.

Trains Isolation Forest model on price history data for
detecting price anomalies.
"""

import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
import statistics

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, PriceHistory, ProductBaselineCache
from src.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class IsolationForestTrainer:
    """
    Trains Isolation Forest model for price anomaly detection.
    
    Features used:
    - price_ratio: Current price / baseline price
    - discount_percent: Discount from original/MSRP
    - price_stability: Historical price stability
    - min_distance: Distance from historical minimum
    - range_position: Position within historical price range
    """
    
    def __init__(
        self,
        model_path: Optional[Path] = None,
        contamination: float = 0.05,
        n_estimators: int = 100,
        min_samples: int = 100,
    ):
        """
        Initialize trainer.
        
        Args:
            model_path: Path to save/load model
            contamination: Expected proportion of outliers in training data
            n_estimators: Number of trees in the forest
            min_samples: Minimum samples needed for training
        """
        self.model_path = model_path or Path("data/models/isolation_forest.pkl")
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.min_samples = min_samples
        
        self._model = None
    
    async def train(self) -> dict:
        """
        Train the Isolation Forest model on price history data.
        
        Returns:
            Dict with training statistics
        """
        logger.info("Starting Isolation Forest training")
        start_time = datetime.utcnow()
        
        async with AsyncSessionLocal() as db:
            # Collect training data
            features, labels = await self._collect_training_data(db)
        
        if len(features) < self.min_samples:
            logger.warning(
                f"Insufficient training data: {len(features)} samples "
                f"(need {self.min_samples})"
            )
            return {
                "success": False,
                "error": "Insufficient training data",
                "samples": len(features),
                "min_required": self.min_samples,
            }
        
        try:
            from sklearn.ensemble import IsolationForest
            
            # Train model
            self._model = IsolationForest(
                contamination=self.contamination,
                n_estimators=self.n_estimators,
                random_state=42,
                n_jobs=-1,
            )
            
            X = np.array(features)
            self._model.fit(X)
            
            # Save model
            self._save_model()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info(
                f"Isolation Forest training complete: {len(features)} samples, "
                f"{duration:.1f}s"
            )
            
            return {
                "success": True,
                "samples": len(features),
                "features": 5,
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
                "duration_seconds": duration,
                "model_path": str(self.model_path),
            }
            
        except ImportError:
            logger.error("scikit-learn not installed, cannot train model")
            return {
                "success": False,
                "error": "scikit-learn not installed",
            }
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _collect_training_data(
        self,
        db: AsyncSession,
    ) -> Tuple[List[List[float]], List[int]]:
        """
        Collect and prepare training data from price history.
        
        Returns:
            Tuple of (features, labels)
            Labels: 1 = normal, -1 = anomaly (for validation)
        """
        features = []
        labels = []
        
        # Get products with baseline cache
        query = select(ProductBaselineCache)
        result = await db.execute(query)
        baselines = list(result.scalars().all())
        
        logger.info(f"Processing {len(baselines)} products for training")
        
        for baseline in baselines:
            # Get price history for this product
            history_query = (
                select(PriceHistory)
                .where(PriceHistory.product_id == baseline.product_id)
                .order_by(PriceHistory.fetched_at.desc())
                .limit(100)
            )
            history_result = await db.execute(history_query)
            history = list(history_result.scalars().all())
            
            if len(history) < 5:
                continue
            
            # Extract features for each price observation
            for entry in history:
                feature_vector = self._extract_features(entry, baseline)
                if feature_vector:
                    features.append(feature_vector)
                    # Assume all historical data is "normal" for unsupervised learning
                    labels.append(1)
        
        return features, labels
    
    def _extract_features(
        self,
        entry: PriceHistory,
        baseline: ProductBaselineCache,
    ) -> Optional[List[float]]:
        """Extract feature vector from a price history entry."""
        if not entry.price or entry.price <= 0:
            return None
        
        if not baseline.current_baseline or baseline.current_baseline <= 0:
            return None
        
        try:
            # Feature 1: Price ratio to baseline
            price_ratio = float(entry.price / baseline.current_baseline)
            
            # Feature 2: Discount from original (if available)
            discount_percent = 0.0
            if entry.original_price and entry.original_price > 0:
                discount_percent = float((1 - entry.price / entry.original_price) * 100)
            
            # Feature 3: Price stability
            stability = baseline.price_stability
            
            # Feature 4: Distance from minimum
            min_distance = 0.0
            if baseline.min_price_seen > 0:
                min_distance = float((baseline.min_price_seen - entry.price) / baseline.min_price_seen)
            
            # Feature 5: Position in price range
            range_position = 0.5
            price_range = float(baseline.max_price_seen - baseline.min_price_seen)
            if price_range > 0:
                range_position = float(entry.price - baseline.min_price_seen) / price_range
                range_position = max(0.0, min(1.0, range_position))
            
            return [
                price_ratio,
                discount_percent,
                stability,
                min_distance,
                range_position,
            ]
            
        except Exception as e:
            logger.debug(f"Feature extraction failed: {e}")
            return None
    
    def _save_model(self) -> None:
        """Save trained model to disk."""
        if self._model is None:
            return
        
        # Ensure directory exists
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.model_path, "wb") as f:
            pickle.dump(self._model, f)
        
        logger.info(f"Model saved to {self.model_path}")
    
    def load_model(self) -> bool:
        """
        Load model from disk.
        
        Returns:
            True if loaded successfully
        """
        if not self.model_path.exists():
            return False
        
        try:
            with open(self.model_path, "rb") as f:
                self._model = pickle.load(f)
            logger.info(f"Model loaded from {self.model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def predict(self, features: List[float]) -> Tuple[bool, float]:
        """
        Predict if a feature vector is anomalous.
        
        Args:
            features: Feature vector
            
        Returns:
            Tuple of (is_anomaly, score)
        """
        if self._model is None:
            if not self.load_model():
                return False, 0.0
        
        try:
            X = np.array([features])
            prediction = self._model.predict(X)[0]
            score = -self._model.decision_function(X)[0]
            
            # Normalize score
            normalized_score = max(0.0, min(1.0, (score + 0.5) / 1.0))
            
            return prediction == -1, normalized_score
            
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return False, 0.0


# Global trainer instance
ml_trainer = IsolationForestTrainer()


async def train_isolation_forest() -> dict:
    """Entry point for scheduler to train model."""
    return await ml_trainer.train()
