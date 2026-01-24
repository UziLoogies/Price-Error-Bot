"""Target price fetcher using embedded JSON extraction."""

from src.ingest.base import RawPriceData
from src.ingest.fetchers.json_endpoint import JSONEndpointFetcher


class TargetFetcher(JSONEndpointFetcher):
    """Fetch Target prices from embedded __TGT_DATA__ JSON."""

    def __init__(self):
        super().__init__(
            store_name="target",
            base_url="https://www.target.com/p/",
            endpoint_template="",  # Not used, we extract from HTML
            price_path="product.price.current_retail",
            title_path="product.title",
            extract_from_html=True,
            json_selector="__TGT_DATA__",
        )

    async def fetch(self, identifier: str) -> RawPriceData:
        """Override to handle Target's URL format."""
        # Target uses A-XXXXXXX format for product IDs
        url = f"{self.base_url}{identifier}"
        result = await super().fetch(identifier)
        result.url = url
        return result
