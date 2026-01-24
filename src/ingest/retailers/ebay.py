"""eBay price fetcher for Buy It Now listings."""

import logging

from src.ingest.fetchers.static import StaticHTMLFetcher

logger = logging.getLogger(__name__)


class eBayFetcher(StaticHTMLFetcher):
    """
    Fetcher for eBay Buy It Now listings.
    
    This fetcher focuses on fixed-price listings only.
    Auctions are excluded to avoid false price errors.
    """

    def __init__(self):
        super().__init__(
            store_name="ebay",
            base_url="https://www.ebay.com/itm/",
            price_selector=[
                "#prcIsum",
                ".x-price-primary span[itemprop='price']",
                ".x-bin-price__content .ux-textspans",
                "[data-testid='x-price-primary']",
                ".notranslate",
            ],
            title_selector="h1.x-item-title__mainTitle span, h1[itemprop='name'], h1.product-title",
            original_price_selector=[
                ".x-price-was .ux-textspans--STRIKETHROUGH",
                ".x-additional-info__listPrice",
                ".vi-original-price",
                ".was-price",
            ],
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from item ID."""
        # eBay URLs are like:
        # https://www.ebay.com/itm/123456789012
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}{identifier}"
