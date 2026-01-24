"""Walmart price fetcher using internal JSON endpoints."""

from src.ingest.fetchers.json_endpoint import JSONEndpointFetcher


class WalmartFetcher(JSONEndpointFetcher):
    """Fetch Walmart prices from internal JSON endpoints."""

    def __init__(self):
        super().__init__(
            store_name="walmart",
            base_url="https://www.walmart.com",
            endpoint_template="{base}/api/item-page/{identifier}",
            price_path="priceInfo.currentPrice.price",
            title_path="name",
            extract_from_html=False,
        )

    def _build_product_url(self, identifier: str) -> str:
        """Build Walmart product URL from item ID."""
        return f"{self.base_url}/ip/{identifier}"
