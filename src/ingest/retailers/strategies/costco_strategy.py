"""Costco retailer strategy."""

from __future__ import annotations

from decimal import Decimal

from src.ingest.retailers.strategies.base import RetailerStrategy, StrategyDecision


class CostcoStrategy(RetailerStrategy):
    store = "costco"

    def validate(self, product, normalized_price, baseline, context) -> StrategyDecision:
        if normalized_price.availability == "out_of_stock":
            return StrategyDecision(allowed=False, reason="Costco item out of stock")

        evidence = ["in_stock"]
        if self._is_warehouse_markdown(normalized_price.current_price) or (
            context and context.get("signal_type") == "clearance"
        ):
            return StrategyDecision(
                allowed=True,
                reason="Costco warehouse markdown",
                confidence_adjustment=0.05,
                evidence_requirements=evidence,
            )

        return StrategyDecision(
            allowed=True,
            reason="Costco validation",
            confidence_adjustment=0.0,
            evidence_requirements=evidence,
        )

    @staticmethod
    def _is_warehouse_markdown(price: Decimal | None) -> bool:
        if price is None:
            return False
        cents = int((price * 100) % 100)
        return cents in {0, 88, 97}
