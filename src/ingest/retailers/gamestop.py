"""GameStop price fetcher."""

import logging

from src.ingest.fetchers.headless import HeadlessBrowserFetcher

logger = logging.getLogger(__name__)


class GameStopFetcher(HeadlessBrowserFetcher):
    """
    Fetcher for GameStop products.
    
    GameStop uses heavy JavaScript rendering for pricing.
    They have new, pre-owned, and digital pricing tiers.
    """
    
    # Price selectors ordered by priority
    PRICE_SELECTORS = [
        ".actual-price",
        "[data-testid='actual-price']",
        ".primary-product-price .price",
        ".sale-price",
        "[data-price]",
        ".price-box .price",
    ]
    
    # Original price selectors
    ORIGINAL_PRICE_SELECTORS = [
        ".regular-price",
        "[data-testid='regular-price']",
        ".strike-price",
        ".original-price",
        ".price-box .was-price",
    ]

    def __init__(self):
        super().__init__(
            store_name="gamestop",
            base_url="https://www.gamestop.com/products/",
            price_selector=self.PRICE_SELECTORS,
            title_selector="h1.product-name, h1[data-testid='product-title'], h1.pdp-title",
            original_price_selector=self.ORIGINAL_PRICE_SELECTORS,
            per_selector_timeout=5000,
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from product ID."""
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}{identifier}"
