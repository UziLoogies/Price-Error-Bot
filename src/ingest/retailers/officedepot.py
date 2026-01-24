"""Office Depot price fetcher."""

import logging

from src.ingest.fetchers.static import StaticHTMLFetcher

logger = logging.getLogger(__name__)


class OfficeDepotFetcher(StaticHTMLFetcher):
    """
    Fetcher for Office Depot products.
    
    Office Depot has a mix of static and dynamic pricing.
    Good for office supplies, electronics, and furniture.
    """

    def __init__(self):
        super().__init__(
            store_name="officedepot",
            base_url="https://www.officedepot.com/a/products/",
            price_selector=[
                ".price_column .price",
                ".pricing .final-price",
                "[data-price]",
                ".sale-price",
                ".product-price .price",
            ],
            title_selector="h1.product_title, h1[itemprop='name'], .pdp-title h1",
            original_price_selector=[
                ".price_column .was-price",
                ".pricing .was-price",
                ".original-price",
                ".strike-price",
            ],
        )
    
    def _build_url(self, identifier: str) -> str:
        """Build product URL from product ID."""
        # Office Depot URLs are like:
        # https://www.officedepot.com/a/products/123456/product-name/
        if identifier.startswith("http"):
            return identifier
        return f"{self.base_url}{identifier}/"
