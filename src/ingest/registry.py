"""Fetcher registry for retailer implementations."""

import logging
from typing import Type

from src.ingest.base import BaseFetcher
from src.ingest.retailers.amazon import AmazonFetcher
from src.ingest.retailers.bestbuy import BestBuyFetcher
from src.ingest.retailers.costco import CostcoFetcher
from src.ingest.retailers.newegg import NeweggFetcher
from src.ingest.retailers.target import TargetFetcher
from src.ingest.retailers.walmart import WalmartFetcher
from src.ingest.retailers.macys import MacysFetcher
from src.ingest.retailers.homedepot import HomeDepotFetcher
from src.ingest.retailers.lowes import LowesFetcher
from src.ingest.retailers.microcenter import MicroCenterFetcher
from src.ingest.retailers.gamestop import GameStopFetcher
from src.ingest.retailers.bhphotovideo import BHPhotoVideoFetcher
from src.ingest.retailers.kohls import KohlsFetcher
from src.ingest.retailers.officedepot import OfficeDepotFetcher
from src.ingest.retailers.ebay import eBayFetcher

logger = logging.getLogger(__name__)


class FetcherRegistry:
    """Registry for retailer fetchers."""

    _fetchers: dict[str, Type[BaseFetcher]] = {
        "amazon_us": AmazonFetcher,
        "walmart": WalmartFetcher,
        "bestbuy": BestBuyFetcher,
        "target": TargetFetcher,
        "costco": CostcoFetcher,
        "newegg": NeweggFetcher,
        "macys": MacysFetcher,
        "homedepot": HomeDepotFetcher,
        "lowes": LowesFetcher,
        "microcenter": MicroCenterFetcher,
        "gamestop": GameStopFetcher,
        "bhphotovideo": BHPhotoVideoFetcher,
        "kohls": KohlsFetcher,
        "officedepot": OfficeDepotFetcher,
        "ebay": eBayFetcher,
    }

    _instances: dict[str, BaseFetcher] = {}

    @classmethod
    def get_fetcher(cls, store: str) -> BaseFetcher:
        """
        Get or create fetcher instance for a store.

        Args:
            store: Store identifier

        Returns:
            Fetcher instance

        Raises:
            ValueError: If store is not registered
        """
        if store not in cls._fetchers:
            raise ValueError(
                f"Unknown store: {store}. Available: {list(cls._fetchers.keys())}"
            )

        # Lazy initialization
        if store not in cls._instances:
            fetcher_class = cls._fetchers[store]
            cls._instances[store] = fetcher_class()
            logger.info(f"Initialized fetcher for store: {store}")

        return cls._instances[store]

    @classmethod
    def register_fetcher(cls, store: str, fetcher_class: Type[BaseFetcher]) -> None:
        """
        Register a new fetcher class.

        Args:
            store: Store identifier
            fetcher_class: Fetcher class to register
        """
        cls._fetchers[store] = fetcher_class
        logger.info(f"Registered fetcher for store: {store}")

    @classmethod
    def list_stores(cls) -> list[str]:
        """List all registered store identifiers."""
        return list(cls._fetchers.keys())

    @classmethod
    async def cleanup(cls) -> None:
        """Close all fetcher instances."""
        for store, fetcher in cls._instances.items():
            try:
                await fetcher.close()
            except Exception as e:
                logger.error(f"Error closing fetcher for {store}: {e}")

        cls._instances.clear()
