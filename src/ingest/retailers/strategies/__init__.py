"""Retailer strategy registry."""

from __future__ import annotations

from src.ingest.retailers.strategies.base import StrategyDecision, RetailerStrategy
from src.ingest.retailers.strategies.amazon_strategy import AmazonStrategy
from src.ingest.retailers.strategies.walmart_strategy import WalmartStrategy
from src.ingest.retailers.strategies.costco_strategy import CostcoStrategy
from src.ingest.retailers.strategies.ebay_strategy import EbayStrategy
from src.ingest.retailers.strategies.default_strategy import DefaultStrategy
from src.ingest.retailers.strategies.bestbuy_strategy import BestBuyStrategy
from src.ingest.retailers.strategies.target_strategy import TargetStrategy
from src.ingest.retailers.strategies.newegg_strategy import NeweggStrategy
from src.ingest.retailers.strategies.macys_strategy import MacysStrategy
from src.ingest.retailers.strategies.homedepot_strategy import HomeDepotStrategy
from src.ingest.retailers.strategies.lowes_strategy import LowesStrategy
from src.ingest.retailers.strategies.microcenter_strategy import MicroCenterStrategy
from src.ingest.retailers.strategies.gamestop_strategy import GameStopStrategy
from src.ingest.retailers.strategies.bhphotovideo_strategy import BHPhotoVideoStrategy
from src.ingest.retailers.strategies.kohls_strategy import KohlsStrategy
from src.ingest.retailers.strategies.officedepot_strategy import OfficeDepotStrategy


_STRATEGIES = {
    "amazon_us": AmazonStrategy(),
    "walmart": WalmartStrategy(),
    "costco": CostcoStrategy(),
    "ebay": EbayStrategy(),
    "bestbuy": BestBuyStrategy(),
    "target": TargetStrategy(),
    "newegg": NeweggStrategy(),
    "macys": MacysStrategy(),
    "homedepot": HomeDepotStrategy(),
    "lowes": LowesStrategy(),
    "microcenter": MicroCenterStrategy(),
    "gamestop": GameStopStrategy(),
    "bhphotovideo": BHPhotoVideoStrategy(),
    "kohls": KohlsStrategy(),
    "officedepot": OfficeDepotStrategy(),
}


def get_strategy_for_store(store: str) -> RetailerStrategy:
    """Return strategy instance for store."""
    if not store:
        return DefaultStrategy()
    return _STRATEGIES.get(store.lower(), DefaultStrategy())


__all__ = [
    "StrategyDecision",
    "RetailerStrategy",
    "get_strategy_for_store",
]
