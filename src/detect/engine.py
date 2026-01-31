"""Price error detection engine."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.llm_anomaly_reviewer import llm_anomaly_reviewer
from src.config import settings
from src.db.models import Product, PriceHistory, Rule as RuleModel
from src.detect.anomaly_detector import anomaly_detector
from src.detect.rules import Rule, RuleType
from src.normalize.processor import NormalizedPrice

logger = logging.getLogger(__name__)


class DetectionResult:
    """Result of price detection."""

    def __init__(
        self,
        triggered: bool,
        rule: Rule | None = None,
        reason: str = "",
        confidence: float = 1.0,
    ):
        self.triggered = triggered
        self.rule = rule
        self.reason = reason
        self.confidence = confidence


class DetectionEngine:
    """Engine for detecting price errors using rules."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def detect(
        self,
        product: Product,
        normalized_price: NormalizedPrice,
    ) -> DetectionResult:
        """
        Detect if a price is an error using configured rules.

        Args:
            product: Product database model
            normalized_price: Normalized price data

        Returns:
            DetectionResult with detection outcome
        """
        # Skip if out of stock (unless very high confidence)
        if normalized_price.availability == "out_of_stock" and normalized_price.confidence < 0.8:
            return DetectionResult(
                triggered=False,
                reason="Product out of stock",
                confidence=normalized_price.confidence,
            )

        # Get enabled rules, sorted by priority
        rules_query = select(RuleModel).where(
            RuleModel.enabled == True
        ).order_by(RuleModel.priority.desc(), RuleModel.id.asc())

        result = await self.db.execute(rules_query)
        rule_models = result.scalars().all()

        if not rule_models:
            return DetectionResult(
                triggered=False,
                reason="No rules configured",
            )

        # Get baseline price (average of last 30 days)
        baseline_price = await self._get_baseline_price(product.id)

        # Get previous price
        previous_price = await self._get_previous_price(product.id)

        # Check each rule
        for rule_model in rule_models:
            rule = Rule(
                id=rule_model.id,
                name=rule_model.name,
                rule_type=RuleType(rule_model.rule_type),
                threshold=rule_model.threshold,
                enabled=rule_model.enabled,
                priority=rule_model.priority,
            )

            triggered, reason = rule.check(
                current_price=normalized_price.current_price,
                baseline_price=baseline_price or product.baseline_price,
                msrp=normalized_price.msrp or product.msrp,
                previous_price=previous_price,
            )

            if triggered:
                # Additional checks
                if rule.rule_type == RuleType.VELOCITY_CHECK:
                    velocity_ok = await self._check_velocity(product.id)
                    if not velocity_ok:
                        logger.warning(
                            f"Velocity check failed for {product.sku}, "
                            "likely bad data"
                        )
                        continue

                # Hybrid approach: Fast statistical detection + ML + LLM review
                confidence = normalized_price.confidence * 0.9  # Slight reduction
                
                # Run ML anomaly detection if enabled
                ml_result = None
                if settings.ai_anomaly_detection_enabled:
                    try:
                        ml_result = await anomaly_detector.detect(
                            db=self.db,
                            product_id=product.id,
                            current_price=normalized_price.current_price,
                            original_price=normalized_price.original_price,
                        )
                        
                        # Boost confidence if ML agrees
                        if ml_result.is_anomaly and ml_result.anomaly_score > 0.7:
                            confidence = min(1.0, confidence + 0.1)
                            reason += f" (ML score: {ml_result.anomaly_score:.2f})"
                    except Exception as e:
                        logger.warning(f"ML anomaly detection failed: {e}")
                
                # LLM review for high-confidence candidates
                if settings.ai_llm_review_enabled and ml_result and ml_result.anomaly_score >= settings.ai_llm_review_threshold:
                    try:
                        llm_review = await self._review_with_llm(
                            product=product,
                            current_price=normalized_price.current_price,
                            ml_result=ml_result,
                        )
                        
                        # Adjust confidence based on LLM review
                        if not llm_review.is_valid:
                            # LLM says it's not a valid anomaly
                            logger.info(
                                f"LLM review rejected anomaly for {product.sku}: "
                                f"{llm_review.explanation}"
                            )
                            continue  # Skip this detection
                        
                        confidence = max(0.0, min(1.0, confidence + llm_review.confidence_adjustment))
                        if llm_review.explanation:
                            reason += f" | LLM: {llm_review.explanation[:100]}"
                    except Exception as e:
                        logger.warning(f"LLM review failed: {e}")
                        # Continue without LLM review if it fails

                logger.info(
                    f"Price error detected for {product.sku}: {reason} "
                    f"(Rule: {rule.name or rule.rule_type.value}, "
                    f"confidence: {confidence:.2f})"
                )

                return DetectionResult(
                    triggered=True,
                    rule=rule,
                    reason=reason,
                    confidence=confidence,
                )

        return DetectionResult(
            triggered=False,
            reason="No rules triggered",
            confidence=normalized_price.confidence,
        )

    async def _get_baseline_price(self, product_id: int) -> Optional[Decimal]:
        """Get baseline price (average of last 30 days)."""
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        query = select(
            func.avg(PriceHistory.price)
        ).where(
            PriceHistory.product_id == product_id,
            PriceHistory.fetched_at >= thirty_days_ago,
            PriceHistory.confidence >= 0.7,  # Only high-confidence prices
        )

        result = await self.db.execute(query)
        avg_price = result.scalar()

        if avg_price:
            return Decimal(str(avg_price))
        return None

    async def _get_previous_price(self, product_id: int) -> Optional[Decimal]:
        """Get the most recent previous price."""
        query = select(PriceHistory.price).where(
            PriceHistory.product_id == product_id
        ).order_by(PriceHistory.fetched_at.desc()).limit(1)

        result = await self.db.execute(query)
        price = result.scalar()

        if price:
            return Decimal(str(price))
        return None

    async def _check_velocity(self, product_id: int) -> bool:
        """
        Check if price has changed too many times recently (likely bad data).

        Returns True if velocity is acceptable, False if suspicious.
        """
        ten_minutes_ago = datetime.utcnow() - timedelta(minutes=10)

        # Count distinct prices in last 10 minutes
        query = select(
            func.count(func.distinct(PriceHistory.price))
        ).where(
            PriceHistory.product_id == product_id,
            PriceHistory.fetched_at >= ten_minutes_ago,
        )

        result = await self.db.execute(query)
        distinct_prices = result.scalar() or 0

        # If price changed more than 3 times in 10 minutes, likely bad data
        return distinct_prices <= 3

    async def update_baseline_price(self, product_id: int) -> None:
        """Update baseline price for a product."""
        baseline = await self._get_baseline_price(product_id)

        if baseline:
            query = select(Product).where(Product.id == product_id)
            result = await self.db.execute(query)
            product = result.scalar_one_or_none()

            if product:
                product.baseline_price = baseline
                await self.db.commit()
                logger.info(f"Updated baseline price for product {product_id}: ${baseline:.2f}")
    
    async def _review_with_llm(
        self,
        product: Product,
        current_price: Decimal,
        ml_result,
    ):
        """
        Review anomaly detection result with LLM.
        
        Args:
            product: Product
            current_price: Current price
            ml_result: Anomaly detection result
            
        Returns:
            LLMReview object
        """
        return await llm_anomaly_reviewer.review_anomaly(
            product=product,
            current_price=current_price,
            ml_result=ml_result,
            db=self.db,
        )