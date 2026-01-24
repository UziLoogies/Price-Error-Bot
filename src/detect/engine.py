"""Price error detection engine."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Product, PriceHistory, Rule as RuleModel
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

                # Combine confidence scores
                confidence = normalized_price.confidence * 0.9  # Slight reduction

                logger.info(
                    f"Price error detected for {product.sku}: {reason} "
                    f"(Rule: {rule.name or rule.rule_type.value})"
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
