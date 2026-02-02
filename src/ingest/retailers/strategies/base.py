"""Retailer-specific strategy base classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.db.models import Product
from src.detect.baseline import ProductBaseline
from src.normalize.processor import NormalizedPrice


@dataclass
class StrategyDecision:
    """Decision result from a retailer strategy."""

    allowed: bool = True
    reason: Optional[str] = None
    confidence_adjustment: float = 0.0
    evidence_requirements: list[str] = field(default_factory=list)


class RetailerStrategy:
    """Base retailer strategy implementation."""

    store: str = "generic"

    def validate(
        self,
        product: Product,
        normalized_price: NormalizedPrice,
        baseline: Optional[ProductBaseline],
        context: dict,
    ) -> StrategyDecision:
        """Validate detection for a retailer."""
        return StrategyDecision(allowed=True)
