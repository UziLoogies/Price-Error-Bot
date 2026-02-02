"""Escalation manager for two-pass scanning."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from src.config import settings
from src.db.models import Candidate
from src.detect.engine import DetectionResult
from src.normalize.processor import NormalizedPrice

logger = logging.getLogger(__name__)


class EscalationManager:
    """Decides whether to escalate to residential proxies."""

    def __init__(self, score_threshold: Optional[float] = None):
        self._score_threshold = score_threshold or settings.escalation_score_threshold

    def should_escalate(
        self,
        error: Optional[str],
        candidate: Candidate,
        detection: Optional[DetectionResult],
        normalized_price: Optional[NormalizedPrice],
    ) -> bool:
        """Return True if a residential verification pass is needed."""
        if error:
            error_lower = error.lower()
            if any(
                token in error_lower
                for token in ["403", "429", "503", "captcha", "blocked", "cloudflare", "timeout"]
            ):
                return True

        if normalized_price and normalized_price.confidence < 0.75:
            return True

        if detection and detection.triggered:
            if detection.confidence >= self._score_threshold:
                return True
            # Escalate if confidence is not very high
            if detection.confidence < 0.9:
                return True

            # Escalate if price is exceptionally low
            if normalized_price and normalized_price.current_price:
                if normalized_price.current_price <= Decimal("1.00"):
                    return True

            # Escalate if discount is extreme
            discount = self._compute_discount_percent(normalized_price)
            if discount is not None and discount >= 70:
                return True

        # Escalate if candidate priority is unusually high
        if candidate.priority_score >= 10:
            return True

        return False

    def _compute_discount_percent(
        self, normalized_price: Optional[NormalizedPrice]
    ) -> Optional[float]:
        """Compute discount percent from MSRP if available."""
        if not normalized_price or not normalized_price.msrp:
            return None
        try:
            if normalized_price.msrp > 0:
                return float(
                    (1 - normalized_price.current_price / normalized_price.msrp) * 100
                )
        except Exception:
            return None
        return None
