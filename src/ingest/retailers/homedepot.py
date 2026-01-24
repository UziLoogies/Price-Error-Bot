"""Home Depot fetcher implementation."""

from src.ingest.fetchers.static import StaticHTMLFetcher


class HomeDepotFetcher(StaticHTMLFetcher):
    """
    Fetcher for Home Depot products.
    
    Home Depot renders prices server-side, so static HTML fetching works.
    """

    def __init__(self):
        super().__init__(
            store_name="homedepot",
            base_url="https://www.homedepot.com/p/-/",
            price_selector=".price-format__main-price span, [data-automation-id='main-price'], .price__dollars",
            title_selector=".product-title__title, h1.sui-font-bold",
            original_price_selector=".price-format__strike-price, [data-automation-id='was-price']",
            use_proxy=True,
        )

    def _build_url(self, identifier: str) -> str:
        """
        Build Home Depot product URL from SKU.
        
        Args:
            identifier: Home Depot product SKU (numeric)
        """
        return f"https://www.homedepot.com/p/-/{identifier}"
