"""Macy's fetcher implementation."""

from src.ingest.fetchers.headless import HeadlessBrowserFetcher


class MacysFetcher(HeadlessBrowserFetcher):
    """
    Fetcher for Macy's products.
    
    Macy's uses heavy JavaScript rendering, so we need headless browser.
    """
    
    # Price selectors ordered by priority
    PRICE_SELECTORS = [
        ".price .lowest-sale-price",
        "[data-auto='product-price'] .c-price__sale",
        ".price-sales",
        ".c-price .c-price__sale",
        ".price .price-now",
    ]
    
    # Original price selectors
    ORIGINAL_PRICE_SELECTORS = [
        ".price .regular-price",
        "[data-auto='product-price'] .c-price__original",
        ".price-regular",
        ".c-price .c-price__was",
    ]

    def __init__(self):
        super().__init__(
            store_name="macys",
            base_url="https://www.macys.com/shop/product/-?ID=",
            price_selector=self.PRICE_SELECTORS,
            title_selector=".product-name h1, [data-auto='product-title']",
            original_price_selector=self.ORIGINAL_PRICE_SELECTORS,
            wait_timeout=35000,
            per_selector_timeout=4000,
            use_proxy=True,
        )

    def _build_url(self, identifier: str) -> str:
        """
        Build Macy's product URL from product ID.
        
        Args:
            identifier: Macy's product ID
        """
        return f"https://www.macys.com/shop/product/-?ID={identifier}"
