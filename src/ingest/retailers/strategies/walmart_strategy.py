"""Walmart retailer strategy."""

from __future__ import annotations

from decimal import Decimal

from src.ingest.retailers.strategies.base import RetailerStrategy, StrategyDecision


class WalmartStrategy(RetailerStrategy):
    store = "walmart"

    def validate(self, product, normalized_price, baseline, context) -> StrategyDecision:
        if normalized_price.availability == "out_of_stock":
            return StrategyDecision(allowed=False, reason="Walmart item out of stock")

        confidence_adjustment = 0.0
        if self._is_clearance_price(normalized_price.current_price):
            confidence_adjustment += 0.05
        if context and context.get("signal_type") == "clearance":
            confidence_adjustment += 0.05

        return StrategyDecision(
            allowed=True,
            reason="Walmart validation",
            confidence_adjustment=confidence_adjustment,
            evidence_requirements=["in_stock"],
        )

    @staticmethod
    def _is_clearance_price(price: Decimal | None) -> bool:
        if price is None:
            return False
        cents = int((price * 100) % 100)
        return cents in {0, 88, 97}
