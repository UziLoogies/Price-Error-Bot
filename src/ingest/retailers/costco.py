"""Costco price fetcher using headless browser with session."""

from src.ingest.fetchers.headless import HeadlessBrowserFetcher


class CostcoFetcher(HeadlessBrowserFetcher):
    """Fetch Costco prices using headless browser (requires session cookie)."""

    # Price selectors ordered by priority
    PRICE_SELECTORS = [
        ".your-price .value",
        ".your-price",
        ".price-value",
        "[data-testid='price']",
        ".product-price span",
        ".price",
    ]

    def __init__(self):
        super().__init__(
            store_name="costco",
            base_url="https://www.costco.com/",
            price_selector=self.PRICE_SELECTORS,
            title_selector="h1.product-title, .product-h1-container h1",
            wait_timeout=40000,  # Costco can be slower
            per_selector_timeout=5000,
        )

    def _build_url(self, identifier: str) -> str:
        """Override to handle Costco's URL format."""
        # Costco uses product ID or item number
        if identifier.startswith("http"):
            return identifier
        # Format: https://www.costco.com/product.{id}.html
        # Remove leading dot from base_url if present
        base = self.base_url.rstrip("/")
        return f"{base}/product.{identifier}.html"
