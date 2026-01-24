"""Micro Center price fetcher."""

import logging

from src.ingest.fetchers.headless import HeadlessBrowserFetcher

logger = logging.getLogger(__name__)


class MicroCenterFetcher(HeadlessBrowserFetcher):
    """
    Fetcher for Micro Center products.
    
    Micro Center uses dynamic pricing and requires headless browser.
    They show different prices for in-store vs online.
    """
    
    # Price selectors ordered by priority
    PRICE_SELECTORS = [
        "#pricing .inStorePrice",
        "#pricing .shipped-price .price",
        "#pricing .normal-price .price",
        ".ProductPricing .price",
        "[itemprop='price']",
        ".price-data",
    ]
    
    # Original price selectors
    ORIGINAL_PRICE_SELECTORS = [
        "#pricing .previous-price",
        "#pricing .was-price",
        ".ProductPricing .previous-price",
        ".msrp-price",
    ]

    def __init__(self):
        super().__init__(
            store_name="microcenter",
            base_url="https://www.microcenter.com/product/",
            price_selector=self.PRICE_SELECTORS,
            title_selector="h1.ProductTitle, h1[data-name], #ProductDetails h1",
            original_price_selector=self.ORIGINAL_PRICE_SELECTORS,
            per_selector_timeout=4000,
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from product ID."""
        # Micro Center URLs typically are like:
        # https://www.microcenter.com/product/123456/product-name
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}{identifier}"
