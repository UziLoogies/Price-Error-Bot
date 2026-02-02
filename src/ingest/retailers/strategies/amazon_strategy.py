"""Amazon retailer strategy."""

from __future__ import annotations

from decimal import Decimal

from src.ingest.retailers.strategies.base import RetailerStrategy, StrategyDecision


class AmazonStrategy(RetailerStrategy):
    store = "amazon_us"

    def validate(self, product, normalized_price, baseline, context) -> StrategyDecision:
        if normalized_price.availability == "out_of_stock":
            return StrategyDecision(allowed=False, reason="Amazon item out of stock")

        evidence = []
        seller_type = None
        if context:
            seller_type = context.get("seller_type")

        if normalized_price.current_price and normalized_price.current_price <= Decimal("1.00"):
            if seller_type not in {"amazon", "fba"}:
                evidence.append("seller_type")

        return StrategyDecision(
            allowed=True,
            reason="Amazon validation",
            confidence_adjustment=0.0,
            evidence_requirements=evidence,
        )
