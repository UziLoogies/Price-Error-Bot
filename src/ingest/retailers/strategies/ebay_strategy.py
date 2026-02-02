"""eBay retailer strategy."""

from __future__ import annotations

from decimal import Decimal

from src.ingest.retailers.strategies.base import RetailerStrategy, StrategyDecision


class EbayStrategy(RetailerStrategy):
    store = "ebay"

    def validate(self, product, normalized_price, baseline, context) -> StrategyDecision:
        sold_median = None
        if context:
            sold_median = context.get("sold_median_price")
            if isinstance(sold_median, str):
                try:
                    sold_median = Decimal(sold_median)
                except Exception:
                    sold_median = None

        confidence_adjustment = 0.0
        if sold_median and normalized_price.current_price:
            if normalized_price.current_price < sold_median * Decimal("0.8"):
                confidence_adjustment += 0.05
            elif normalized_price.current_price > sold_median * Decimal("1.1"):
                return StrategyDecision(
                    allowed=False,
                    reason="Above sold median comps",
                    evidence_requirements=["sold_comps"],
                )

        return StrategyDecision(
            allowed=True,
            reason="eBay comps check",
            confidence_adjustment=confidence_adjustment,
            evidence_requirements=["sold_comps"] if sold_median else [],
        )
