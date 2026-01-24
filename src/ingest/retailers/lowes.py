"""Lowe's fetcher implementation."""

from src.ingest.fetchers.static import StaticHTMLFetcher


class LowesFetcher(StaticHTMLFetcher):
    """
    Fetcher for Lowe's products.
    
    Lowe's renders prices server-side, so static HTML fetching works.
    """

    def __init__(self):
        super().__init__(
            store_name="lowes",
            base_url="https://www.lowes.com/pd/-/",
            price_selector="[data-selector='price-value'], .art-pd-price .main-price, .ProductPriceWrapper span",
            title_selector="h1.prod-title, [data-selector='product-title']",
            original_price_selector=".was-price, .strike-price",
            use_proxy=True,
        )

    def _build_url(self, identifier: str) -> str:
        """
        Build Lowe's product URL from item number.
        
        Args:
            identifier: Lowe's item number (numeric)
        """
        return f"https://www.lowes.com/pd/-/{identifier}"
