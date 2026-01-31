"""ML-based anomaly detection for price errors.

Implements multiple detection methods:
1. Z-Score Detection
2. IQR (Interquartile Range)
3. Isolation Forest (ML)
4. Rate of Change Detection
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.anomaly_features import anomaly_feature_extractor
from src.config import settings
from src.db.models import Product, PriceHistory, ProductBaselineCache
from src.detect.baseline import baseline_calculator, ProductBaseline, PriceStatistics
from src.detect.comparative_pricing import comparative_pricing_engine
from src.detect.msrp_service import msrp_service
from src.utils.model_loader import load_model_with_fallback

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """Result of anomaly detection analysis."""
    
    is_anomaly: bool
    anomaly_score: float              # 0.0-1.0 (higher = more anomalous)
    detection_methods: List[str]      # Methods that flagged anomaly
    confidence: float                 # 0.0-1.0
    z_score: Optional[float] = None
    percentile: Optional[float] = None
    iqr_outlier: bool = False
    isolation_score: Optional[float] = None
    rate_of_change: Optional[float] = None
    gmm_score: Optional[float] = None
    autoencoder_score: Optional[float] = None
    ensemble_score: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    
    @property
    def is_significant(self) -> bool:
        """Check if anomaly is significant (multiple methods agree or high score)."""
        return (
            (len(self.detection_methods) >= 2 and self.is_anomaly) or
            (self.anomaly_score >= 0.8 and self.is_anomaly)
        )
    
    @property
    def detection_summary(self) -> str:
        """Get a summary of detection results."""
        if not self.is_anomaly:
            return "Normal price"
        methods = ", ".join(self.detection_methods)
        return f"Anomaly detected by: {methods} (score: {self.anomaly_score:.2f})"


class AnomalyDetector:
    """
    Multi-method anomaly detector for price data.
    
    Combines statistical methods (Z-score, IQR) with ML (Isolation Forest)
    to detect price anomalies that may indicate pricing errors.
    """
    
    def __init__(
        self,
        z_threshold: float = 2.5,
        iqr_multiplier: float = 1.5,
        rate_of_change_threshold: float = 50.0,
        model_path: Optional[Path] = None,
    ):
        """
        Initialize anomaly detector.
        
        Args:
            z_threshold: Z-score threshold for anomaly detection
            iqr_multiplier: Multiplier for IQR-based detection
            rate_of_change_threshold: Percent change threshold for rate detection
            model_path: Path to saved Isolation Forest model
        """
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier
        self.rate_of_change_threshold = rate_of_change_threshold
        self.model_path = model_path or Path("data/models/isolation_forest.pkl")
        
        self._isolation_model = None
        self._gmm_model = None
        self._autoencoder_model = None
        self._scaler = StandardScaler()
        self._model_loaded = False
        self._use_enhanced_ml = settings.ai_anomaly_detection_enabled
    
    def _load_model(self) -> bool:
        """
        Load the Isolation Forest model if available.
        
        Uses shared utility function for consistent security validation
        and error handling. Model files must be from trusted sources only.
        """
        if self._model_loaded:
            return self._isolation_model is not None
        
        self._model_loaded = True
        
        try:
            self._isolation_model = load_model_with_fallback(self.model_path)
            return True
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            logger.warning(f"Failed to load Isolation Forest model: {e}")
            return False
    
    async def detect(
        self,
        db: AsyncSession,
        product_id: int,
        current_price: Decimal,
        original_price: Optional[Decimal] = None,
    ) -> AnomalyResult:
        """
        Detect if a price is anomalous using multiple methods.
        
        Args:
            db: Database session
            product_id: Product ID
            current_price: Current price to check
            original_price: Strikethrough/was price if available
            
        Returns:
            AnomalyResult with detection details
        """
        detection_methods = []
        reasons = []
        scores = []
        
        z_score = None
        percentile = None
        iqr_outlier = False
        isolation_score = None
        rate_of_change = None
        
        # Get baseline and statistics
        baseline = await baseline_calculator.calculate_baseline(db, product_id)
        stats = await baseline_calculator.calculate_statistics(db, product_id)
        
        # 1. Z-Score Detection
        if stats and stats.std_dev > 0:
            z_score = float(current_price - stats.mean) / stats.std_dev
            percentile = self._z_to_percentile(z_score)
            
            if z_score < -self.z_threshold:
                detection_methods.append("z_score")
                reasons.append(f"Z-score {z_score:.2f} below threshold -{self.z_threshold}")
                scores.append(min(1.0, abs(z_score) / 4.0))
        
        # 2. IQR Detection
        history = await baseline_calculator.get_price_history(db, product_id)
        if len(history) >= 4:
            iqr_result = self._check_iqr(
                current_price,
                [float(h.price) for h in history if h.price > 0]
            )
            iqr_outlier = iqr_result["is_outlier"]
            
            if iqr_outlier:
                detection_methods.append("iqr")
                reasons.append(f"Below IQR lower bound (${iqr_result['lower_bound']:.2f})")
                scores.append(0.7)
        
        # 3. Isolation Forest Detection
        if self._load_model() and baseline:
            isolation_result = self._check_isolation_forest(
                current_price,
                baseline,
                original_price,
            )
            isolation_score = isolation_result["score"]
            
            if isolation_result["is_anomaly"]:
                detection_methods.append("isolation_forest")
                reasons.append(f"Isolation Forest score: {isolation_score:.3f}")
                scores.append(isolation_score)
        
        # Enhanced ML methods (if enabled)
        gmm_score = None
        autoencoder_score = None
        if self._use_enhanced_ml:
            # 3a. Gaussian Mixture Model Detection
            gmm_result = await self._detect_with_gmm(
                db,
                product_id,
                current_price,
            )
            if gmm_result:
                gmm_score = gmm_result["score"]
                if gmm_result["is_anomaly"]:
                    detection_methods.append("gmm")
                    reasons.append(f"GMM score: {gmm_score:.3f}")
                    scores.append(gmm_score)
            
            # 3b. Autoencoder Detection
            ae_result = await self._detect_with_autoencoder(
                db,
                product_id,
                current_price,
            )
            if ae_result:
                autoencoder_score = ae_result["score"]
                if ae_result["is_anomaly"]:
                    detection_methods.append("autoencoder")
                    reasons.append(f"Autoencoder score: {autoencoder_score:.3f}")
                    scores.append(autoencoder_score)
        
        # 4. Rate of Change Detection
        if history and len(history) >= 2:
            recent_prices = [float(h.price) for h in history[:5] if h.price > 0]
            if recent_prices:
                avg_recent = statistics.mean(recent_prices)
                if avg_recent > 0:
                    rate_of_change = ((avg_recent - float(current_price)) / avg_recent) * 100
                    
                    if rate_of_change >= self.rate_of_change_threshold:
                        detection_methods.append("rate_of_change")
                        reasons.append(f"{rate_of_change:.1f}% drop from recent average")
                        scores.append(min(1.0, rate_of_change / 100))
        
        # 5. Below Historical Minimum Check
        if baseline and current_price < baseline.min_price_seen:
            detection_methods.append("below_minimum")
            discount = float((1 - current_price / baseline.min_price_seen) * 100)
            reasons.append(f"Below historical minimum by {discount:.1f}%")
            scores.append(min(1.0, discount / 50))
        
        # Calculate overall anomaly score and confidence
        is_anomaly = len(detection_methods) > 0
        
        if scores:
            anomaly_score = sum(scores) / len(scores)
            # Boost score if multiple methods agree
            if len(detection_methods) >= 2:
                anomaly_score = min(1.0, anomaly_score * 1.2)
            if len(detection_methods) >= 3:
                anomaly_score = min(1.0, anomaly_score * 1.1)
        else:
            anomaly_score = 0.0
        
        # Ensemble voting (if multiple ML methods available)
        ensemble_score = None
        if self._use_enhanced_ml and (isolation_score is not None or gmm_score is not None or autoencoder_score is not None):
            ml_scores = [s for s in [isolation_score, gmm_score, autoencoder_score] if s is not None]
            if len(ml_scores) >= 2:
                ensemble_score = np.mean(ml_scores)
                # If ensemble agrees, boost confidence
                if all(s > 0.5 for s in ml_scores):
                    detection_methods.append("ensemble")
                    reasons.append(f"Ensemble agreement (avg: {ensemble_score:.3f})")
                    scores.append(ensemble_score)
        
        # Recalculate anomaly_score after ensemble additions
        if scores:
            anomaly_score = sum(scores) / len(scores)
            # Boost score if multiple methods agree
            if len(detection_methods) >= 2:
                anomaly_score = min(1.0, anomaly_score * 1.2)
            if len(detection_methods) >= 3:
                anomaly_score = min(1.0, anomaly_score * 1.1)
        else:
            anomaly_score = 0.0
        
        # Update is_anomaly based on final score
        is_anomaly = anomaly_score > 0.5 or len(detection_methods) > 0
        
        # Confidence based on data quality and method agreement
        confidence = self._calculate_confidence(
            baseline,
            len(detection_methods),
            len(history) if history else 0,
        )
        
        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_score=anomaly_score,
            detection_methods=detection_methods,
            confidence=confidence,
            z_score=z_score,
            percentile=percentile,
            iqr_outlier=iqr_outlier,
            isolation_score=isolation_score,
            rate_of_change=rate_of_change,
            gmm_score=gmm_score,
            autoencoder_score=autoencoder_score,
            ensemble_score=ensemble_score,
            reasons=reasons,
        )
    
    def _z_to_percentile(self, z_score: float) -> float:
        """Convert Z-score to approximate percentile."""
        # Simplified approximation
        if z_score < -3:
            return 0.1
        elif z_score > 3:
            return 99.9
        else:
            return max(0.1, min(99.9, 50 + z_score * 15))
    
    def _check_iqr(
        self,
        price: Decimal,
        prices: List[float],
    ) -> Dict[str, Any]:
        """Check if price is an IQR outlier."""
        if len(prices) < 4:
            return {"is_outlier": False, "lower_bound": 0, "upper_bound": 0}
        
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        
        q1 = sorted_prices[q1_idx]
        q3 = sorted_prices[q3_idx]
        iqr = q3 - q1
        
        lower_bound = q1 - self.iqr_multiplier * iqr
        upper_bound = q3 + self.iqr_multiplier * iqr
        
        is_outlier = float(price) < lower_bound
        
        return {
            "is_outlier": is_outlier,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
        }
    
    def _check_isolation_forest(
        self,
        current_price: Decimal,
        baseline: ProductBaseline,
        original_price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """Check price using Isolation Forest model."""
        if self._isolation_model is None:
            return {"is_anomaly": False, "score": 0.0}
        
        try:
            # Prepare features
            features = self._prepare_features(current_price, baseline, original_price)
            features_array = np.array([features])
            
            # Predict
            prediction = self._isolation_model.predict(features_array)[0]
            score = -self._isolation_model.decision_function(features_array)[0]
            
            # Normalize score to 0-1 range
            normalized_score = max(0.0, min(1.0, (score + 0.5) / 1.0))
            
            return {
                "is_anomaly": prediction == -1,
                "score": normalized_score,
                "raw_score": score,
            }
        except Exception as e:
            logger.warning(f"Isolation Forest prediction failed: {e}")
            return {"is_anomaly": False, "score": 0.0}
    
    def _prepare_features(
        self,
        current_price: Decimal,
        baseline: ProductBaseline,
        original_price: Optional[Decimal] = None,
    ) -> List[float]:
        """Prepare features for Isolation Forest model."""
        # Feature 1: Price ratio to baseline
        price_ratio = float(current_price / baseline.current_baseline) if baseline.current_baseline > 0 else 1.0
        
        # Feature 2: Discount from original/strikethrough
        discount_percent = 0.0
        if original_price and original_price > 0:
            discount_percent = float((1 - current_price / original_price) * 100)
        
        # Feature 3: Price stability
        stability = baseline.price_stability
        
        # Feature 4: Distance from min
        min_distance = 0.0
        if baseline.min_price_seen > 0:
            min_distance = float((baseline.min_price_seen - current_price) / baseline.min_price_seen)
        
        # Feature 5: Range position (0 = at min, 1 = at max)
        range_position = 0.5
        price_range = float(baseline.max_price_seen - baseline.min_price_seen)
        if price_range > 0:
            range_position = float(current_price - baseline.min_price_seen) / price_range
        
        return [
            price_ratio,
            discount_percent,
            stability,
            min_distance,
            range_position,
        ]
    
    def _calculate_confidence(
        self,
        baseline: Optional[ProductBaseline],
        methods_triggered: int,
        history_count: int,
    ) -> float:
        """Calculate confidence in the detection result."""
        confidence = 0.5
        
        # More history = higher confidence
        if history_count >= 20:
            confidence += 0.2
        elif history_count >= 10:
            confidence += 0.1
        
        # Multiple methods agreeing = higher confidence
        if methods_triggered >= 3:
            confidence += 0.2
        elif methods_triggered >= 2:
            confidence += 0.1
        
        # Stable prices = higher confidence in anomaly detection
        if baseline and baseline.price_stability > 0.8:
            confidence += 0.1
        
        return min(1.0, confidence)
    
    async def detect_for_sku(
        self,
        db: AsyncSession,
        store: str,
        sku: str,
        current_price: Decimal,
        original_price: Optional[Decimal] = None,
    ) -> AnomalyResult:
        """
        Detect anomaly for a product by store and SKU.
        
        Args:
            db: Database session
            store: Store identifier
            sku: Product SKU
            current_price: Current price
            original_price: Strikethrough price
            
        Returns:
            AnomalyResult
        """
        # Find product
        query = select(Product).where(Product.store == store, Product.sku == sku)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            # No history, return non-anomalous result
            return AnomalyResult(
                is_anomaly=False,
                anomaly_score=0.0,
                detection_methods=[],
                confidence=0.3,
                reasons=["No price history available"],
            )
        
        return await self.detect(db, product.id, current_price, original_price)
    
    async def calculate_composite_anomaly_score(
        self,
        db: AsyncSession,
        product: Product,
        current_price: Decimal,
        original_price: Optional[Decimal] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate composite anomaly score combining multiple factors.
        
        Factors:
        - Discount percentage
        - Z-score relative to category
        - Price drop magnitude
        - Historical volatility
        - Comparative pricing deviation
        - MSRP deviation
        
        Args:
            db: Database session
            product: Product object
            current_price: Current price
            original_price: Original/strikethrough price
            category: Category name
            
        Returns:
            Dict with composite score and component scores
        """
        components = {}
        total_score = 0.0
        weights = {
            "discount_percent": 0.25,
            "z_score": 0.20,
            "price_drop": 0.15,
            "volatility": 0.10,
            "comparative": 0.15,
            "msrp_deviation": 0.15,
        }
        
        # 1. Discount percentage
        discount_score = 0.0
        if original_price and original_price > 0:
            discount = float((1 - current_price / original_price) * 100)
            discount_score = min(1.0, discount / 100)  # Normalize to 0-1
        components["discount_percent"] = discount_score
        total_score += discount_score * weights["discount_percent"]
        
        # 2. Z-score (from baseline detection)
        anomaly_result = await self.detect(db, product.id, current_price, original_price)
        z_score_component = 0.0
        if anomaly_result.z_score is not None:
            # Normalize Z-score to 0-1 (negative Z-scores are anomalies)
            if anomaly_result.z_score < 0:
                z_score_component = min(1.0, abs(anomaly_result.z_score) / 4.0)
        components["z_score"] = z_score_component
        total_score += z_score_component * weights["z_score"]
        
        # 3. Price drop magnitude
        price_drop_score = 0.0
        if product.baseline_price and product.baseline_price > 0:
            drop_percent = float((1 - current_price / product.baseline_price) * 100)
            price_drop_score = min(1.0, drop_percent / 100)
        components["price_drop"] = price_drop_score
        total_score += price_drop_score * weights["price_drop"]
        
        # 4. Historical volatility (lower volatility = higher confidence in anomaly)
        volatility_score = 0.0
        baseline = await baseline_calculator.calculate_baseline(db, product.id)
        if baseline and baseline.price_stability is not None:
            # High stability (low volatility) = higher score for anomalies
            volatility_score = 1.0 - baseline.price_stability
        components["volatility"] = volatility_score
        total_score += volatility_score * weights["volatility"]
        
        # 5. Comparative pricing deviation
        comparative_score = 0.0
        comparison = await comparative_pricing_engine.compare_price(
            current_price,
            product.sku,
            category,
        )
        if comparison.is_anomalous:
            comparative_score = comparison.confidence
        components["comparative"] = comparative_score
        total_score += comparative_score * weights["comparative"]
        
        # 6. MSRP deviation
        msrp_score = 0.0
        is_anomalous_msrp = await msrp_service.is_anomalous_msrp_discount(
            current_price,
            product,
        )
        if is_anomalous_msrp:
            msrp = await msrp_service.get_msrp(product)
            if msrp:
                discount = await msrp_service.calculate_msrp_discount(current_price, msrp)
                msrp_score = min(1.0, discount / 100)
        components["msrp_deviation"] = msrp_score
        total_score += msrp_score * weights["msrp_deviation"]
        
        # Normalize total score to 0-1
        composite_score = min(1.0, total_score)
        
        # Calculate confidence
        confidence = self._calculate_composite_confidence(
            components,
            anomaly_result.confidence,
            comparison.confidence if comparison else 0.0,
        )
        
        return {
            "composite_score": composite_score,
            "confidence": confidence,
            "components": components,
            "weights": weights,
            "is_anomalous": composite_score >= 0.6,  # Threshold for anomaly
            "threshold": 0.6,
        }
    
    def _calculate_composite_confidence(
        self,
        components: Dict[str, float],
        baseline_confidence: float,
        comparative_confidence: float,
    ) -> float:
        """Calculate confidence for composite score."""
        # Base confidence from baseline detection
        confidence = baseline_confidence * 0.5
        
        # Boost if comparative pricing agrees
        if comparative_confidence > 0.7:
            confidence += 0.3
        
        # Boost if multiple components are high
        high_components = sum(1 for v in components.values() if v > 0.7)
        if high_components >= 3:
            confidence += 0.2
        elif high_components >= 2:
            confidence += 0.1
        
        return min(1.0, confidence)
    
    async def _detect_with_gmm(
        self,
        db: AsyncSession,
        product_id: int,
        current_price: Decimal,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect anomaly using Gaussian Mixture Model.
        
        Args:
            db: Database session
            product_id: Product ID
            current_price: Current price
            
        Returns:
            Dictionary with is_anomaly and score, or None if insufficient data
        """
        try:
            # Get historical prices
            history = await baseline_calculator.get_price_history(db, product_id, limit=50)
            if len(history) < 10:
                return None
            
            prices = np.array([[float(h.price)] for h in history])
            
            # Fit GMM
            n_components = min(3, len(prices) // 5)  # Adaptive component count
            if n_components < 1:
                return None
            
            gmm = GaussianMixture(n_components=n_components, random_state=42)
            gmm.fit(prices)
            
            # Get log probability for current price
            current_price_array = np.array([[float(current_price)]])
            log_prob = gmm.score_samples(current_price_array)[0]
            
            # Calculate threshold (use percentile of historical log probs)
            hist_log_probs = gmm.score_samples(prices)
            threshold = np.percentile(hist_log_probs, 10)  # Bottom 10% is anomalous
            
            is_anomaly = log_prob < threshold
            
            # Normalize score (lower log prob = higher anomaly score)
            score = max(0.0, min(1.0, 1.0 - (log_prob - threshold) / abs(threshold) if threshold < 0 else 0.5))
            
            return {
                "is_anomaly": is_anomaly,
                "score": float(score),
                "log_prob": float(log_prob),
            }
        except Exception as e:
            logger.warning(f"GMM detection failed: {e}")
            return None
    
    async def _detect_with_autoencoder(
        self,
        db: AsyncSession,
        product_id: int,
        current_price: Decimal,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect anomaly using Autoencoder (reconstruction error).
        
        Note: Full autoencoder implementation would require training a neural network.
        This is a simplified version using feature-based reconstruction error.
        
        Args:
            db: Database session
            product_id: Product ID
            current_price: Current price
            
        Returns:
            Dictionary with is_anomaly and score, or None if insufficient data
        """
        try:
            # Extract features for current price
            features = await anomaly_feature_extractor.extract_features(
                product_id,
                current_price,
                db,
            )
            
            if not features or len(features) < 5:
                return None
            
            # Get historical features (simplified - use price history)
            history = await baseline_calculator.get_price_history(db, product_id, limit=30)
            if len(history) < 10:
                return None
            
            # Build feature matrix from historical prices
            hist_features = []
            for h in history:
                hist_feat = await anomaly_feature_extractor.extract_features(
                    product_id,
                    h.price,
                    db,
                )
                if hist_feat:
                    hist_features.append(list(hist_feat.values()))
            
            if len(hist_features) < 10:
                return None
            
            hist_features_array = np.array(hist_features)
            current_features_array = np.array([list(features.values())])
            
            # Simple reconstruction: use mean of historical features as "reconstruction"
            mean_features = np.mean(hist_features_array, axis=0)
            
            # Calculate reconstruction error (MSE)
            reconstruction_error = np.mean((current_features_array - mean_features) ** 2)
            
            # Calculate threshold (percentile of historical errors)
            hist_errors = []
            for hist_feat in hist_features:
                error = np.mean((hist_feat - mean_features) ** 2)
                hist_errors.append(error)
            
            threshold = np.percentile(hist_errors, 90)  # Top 10% error is anomalous
            
            is_anomaly = reconstruction_error > threshold
            
            # Normalize score
            if threshold > 0:
                score = min(1.0, reconstruction_error / threshold)
            else:
                score = 0.5
            
            return {
                "is_anomaly": is_anomaly,
                "score": float(score),
                "reconstruction_error": float(reconstruction_error),
            }
        except Exception as e:
            logger.warning(f"Autoencoder detection failed: {e}")
            return None


# Global anomaly detector instance
anomaly_detector = AnomalyDetector()
