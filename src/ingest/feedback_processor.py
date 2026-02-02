"""Feedback processor for true/false positive tracking."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, Product, Rule as RuleModel
from src import metrics

logger = logging.getLogger(__name__)


class FeedbackProcessor:
    """Record feedback and update false positive metrics."""

    def __init__(self):
        self._counts: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "false": 0}
        )

    async def record_feedback(
        self,
        db: AsyncSession,
        alert_id: int,
        is_true_positive: bool,
        notes: str | None = None,
    ) -> bool:
        """Record feedback for an alert and update metrics."""
        alert = await db.get(Alert, alert_id)
        if not alert:
            logger.warning("Alert %s not found for feedback", alert_id)
            return False

        product = await db.get(Product, alert.product_id)
        rule = await db.get(RuleModel, alert.rule_id)

        retailer = product.store if product else "unknown"
        rule_type = rule.rule_type if rule else "unknown"

        counts = self._counts[(retailer, rule_type)]
        counts["total"] += 1
        if not is_true_positive:
            counts["false"] += 1
            alert.false_positive_count += 1

        false_rate = counts["false"] / max(1, counts["total"])
        metrics.update_false_positive_rate(retailer, rule_type, false_rate)

        await db.commit()
        return True


# Global feedback processor instance
feedback_processor = FeedbackProcessor()
