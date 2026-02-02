"""Micro Center retailer strategy."""

from __future__ import annotations

from src.ingest.retailers.strategies.base import RetailerStrategy, StrategyDecision


class MicroCenterStrategy(RetailerStrategy):
    store = "microcenter"

    def validate(self, product, normalized_price, baseline, context) -> StrategyDecision:
        return StrategyDecision(allowed=True)
