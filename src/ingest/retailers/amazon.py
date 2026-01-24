"""Amazon price fetcher using headless browser."""

from src.ingest.fetchers.headless import HeadlessBrowserFetcher


class AmazonFetcher(HeadlessBrowserFetcher):
    """Fetch Amazon prices using headless browser (JS-rendered content)."""

    # Comprehensive list of Amazon price selectors (varies by product/layout)
    # Ordered by priority - most common/reliable first
    PRICE_SELECTORS = [
        # Primary price selectors (most common layouts)
        "#corePrice_feature_div .a-price .a-offscreen",
        "#apex_offerDisplay_desktop .a-price .a-offscreen",
        ".a-price[data-a-size='xl'] .a-offscreen",
        
        # Buy box prices
        "#price_inside_buybox",
        "#newBuyBoxPrice",
        
        # Price to pay section (reinvent layout)
        ".priceToPay .a-offscreen",
        ".reinventPricePriceToPayMargin .a-offscreen",
        
        # Legacy price blocks
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        
        # Deal and sale prices
        "#dealPriceValue",
        "#apex_desktop .a-price .a-offscreen",
        
        # Kindle/digital prices
        "#kindle-price",
        "#digital-list-price .a-offscreen",
        
        # Subscribe & Save price
        "#snsPrice .a-offscreen",
        
        # Fallback - any visible price (last resort)
        ".a-price:not(.a-text-price) .a-offscreen",
    ]
    
    # Original/strikethrough price selectors
    ORIGINAL_PRICE_SELECTORS = [
        "#corePrice_feature_div .a-text-price .a-offscreen",
        ".a-price.a-text-price .a-offscreen",
        "#listPrice",
        ".basisPrice .a-offscreen",
        "#priceblock_listprice",
    ]
    
    # Indicators that product is unavailable
    UNAVAILABLE_SELECTORS = [
        "#availability .a-color-price",  # "Currently unavailable"
        "#outOfStock",
        "#availability .a-color-state",
    ]

    def __init__(self):
        super().__init__(
            store_name="amazon_us",
            base_url="https://www.amazon.com/dp/",
            price_selector=self.PRICE_SELECTORS,  # Now a list
            title_selector="#productTitle",
            original_price_selector=self.ORIGINAL_PRICE_SELECTORS,  # Now a list
            wait_timeout=45000,
            per_selector_timeout=4000,  # 4 seconds per selector
        )
