"""B&H Photo Video price fetcher."""

import logging

from src.ingest.fetchers.static import StaticHTMLFetcher

logger = logging.getLogger(__name__)


class BHPhotoVideoFetcher(StaticHTMLFetcher):
    """
    Fetcher for B&H Photo Video products.
    
    B&H uses mostly static HTML with some dynamic updates.
    Good for cameras, audio equipment, and electronics.
    """

    def __init__(self):
        super().__init__(
            store_name="bhphotovideo",
            base_url="https://www.bhphotovideo.com/c/product/",
            price_selector=[
                ".price_0",
                "[data-selenium='pricingPrice']",
                ".finalPrice",
                "[data-selenium='finalPrice']",
                ".price-info .price",
            ],
            title_selector="h1[data-selenium='productTitle'], h1.title-product",
            original_price_selector=[
                ".wasPrice",
                "[data-selenium='wasPrice']",
                ".listPrice",
                ".price-info .was-price",
            ],
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from product ID."""
        # B&H URLs are like:
        # https://www.bhphotovideo.com/c/product/1234567-REG/product-name.html
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}{identifier}"
