"""Kohl's price fetcher."""

import logging

from src.ingest.fetchers.headless import HeadlessBrowserFetcher

logger = logging.getLogger(__name__)


class KohlsFetcher(HeadlessBrowserFetcher):
    """
    Fetcher for Kohl's products.
    
    Kohl's uses JavaScript-heavy pages and has complex pricing 
    with Kohl's Cash and stackable coupons.
    """
    
    # Price selectors ordered by priority
    PRICE_SELECTORS = [
        ".prod_price_amount",
        ".prod_price_sale",
        "[data-automation='final-price']",
        ".sale-price",
        ".current-price",
        ".price-sale",
    ]
    
    # Original price selectors
    ORIGINAL_PRICE_SELECTORS = [
        ".prod_price_original",
        ".prod_was_price",
        "[data-automation='regular-price']",
        ".original-price",
        ".was-price",
    ]

    def __init__(self):
        super().__init__(
            store_name="kohls",
            base_url="https://www.kohls.com/product/",
            price_selector=self.PRICE_SELECTORS,
            title_selector="h1.product-title, h1[data-automation='product-title'], .pdp-title",
            original_price_selector=self.ORIGINAL_PRICE_SELECTORS,
            per_selector_timeout=5000,
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from product ID."""
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}prd-{identifier}.jsp"
