"""Category scanner for discovering products from store category pages."""

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from src.ingest.proxy_manager import proxy_rotator, ProxyInfo
from src.ingest.rate_limiter import rate_limiter
from src.config import settings

logger = logging.getLogger(__name__)

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Common bot/blocked page indicators (lowercase match)
BLOCK_PATTERNS = [
    ("access denied", "Access denied"),
    ("forbidden", "Forbidden"),
    ("captcha", "Captcha required"),
    ("verify you are a human", "Human verification required"),
    ("robot check", "Robot check"),
    ("pardon our interruption", "Bot protection"),
    ("automation tools", "Automation blocked"),
    ("request has been blocked", "Request blocked"),
    ("unusual traffic", "Unusual traffic detected"),
    ("enable javascript", "JavaScript required"),
    ("enable cookies", "Cookies required"),
    ("cloudflare", "Cloudflare protection"),
    ("akamai", "Akamai protection"),
    ("incapsula", "Incapsula protection"),
]


class CategoryScanError(RuntimeError):
    """Raised when a category scan fails to fetch usable content."""

    def __init__(self, store: str, url: str, message: str):
        super().__init__(message)
        self.store = store
        self.url = url


def detect_block_reason(html: str) -> Optional[str]:
    """Detect common bot/blocked page signals in HTML."""
    if not html:
        return "Empty response"
    haystack = " ".join(html.lower().split())
    for needle, reason in BLOCK_PATTERNS:
        if needle in haystack:
            return reason
    return None


@dataclass
class DiscoveredProduct:
    """A product discovered from a category page."""
    
    sku: str
    title: str
    url: str
    current_price: Optional[Decimal] = None
    original_price: Optional[Decimal] = None  # Strikethrough/was price
    msrp: Optional[Decimal] = None
    store: str = ""
    image_url: Optional[str] = None
    
    @property
    def discount_percent(self) -> Optional[float]:
        """Calculate discount percentage from original price."""
        if self.original_price and self.current_price and self.original_price > 0:
            return float((1 - self.current_price / self.original_price) * 100)
        if self.msrp and self.current_price and self.msrp > 0:
            return float((1 - self.current_price / self.msrp) * 100)
        return None


class BaseCategoryParser:
    """Base class for store-specific category page parsers."""
    
    store_name: str = ""
    base_url: str = ""
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        """
        Parse a category page and extract products.
        
        Args:
            html: Raw HTML content
            category_url: The category page URL
            
        Returns:
            List of discovered products
        """
        raise NotImplementedError
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """
        Get the URL for the next page of results.
        
        Args:
            html: Current page HTML
            current_url: Current page URL
            
        Returns:
            Next page URL or None if no more pages
        """
        return None  # Override in subclasses
    
    @staticmethod
    def parse_price(price_text: str) -> Optional[Decimal]:
        """Parse price from text."""
        if not price_text:
            return None
        
        # Remove currency symbols, commas, whitespace
        cleaned = price_text.replace("$", "").replace(",", "").strip()
        
        # Extract first number
        match = re.search(r'[\d.]+', cleaned)
        if match:
            try:
                return Decimal(match.group())
            except Exception:
                pass
        return None
    
    @staticmethod
    def extract_sku_from_url(url: str) -> Optional[str]:
        """Extract product SKU/ID from URL."""
        # Common patterns
        patterns = [
            r'/dp/([A-Z0-9]{10})',  # Amazon ASIN
            r'/ip/([0-9]+)',  # Walmart
            r'/p/([A-Za-z0-9-]+)',  # Various
            r'/product/([0-9]+)',  # Various
            r'/([0-9]{6,})',  # Generic numeric ID
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None


class AmazonCategoryParser(BaseCategoryParser):
    """Parser for Amazon category/search pages."""
    
    store_name = "amazon_us"
    base_url = "https://www.amazon.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Amazon search result items - try multiple selectors
        items = parser.css('[data-component-type="s-search-result"]')
        
        # If no items found, try deal page structure
        if not items:
            items = parser.css('[data-testid="deal-card"], .DealCard, .deal-card, [data-deal-id]')
        
        # If still no items, try generic product grid
        if not items:
            items = parser.css('[data-asin]')
        
        # Log what we're finding for debugging
        if not items:
            logger.debug(f"No product items found on Amazon page (checked 3 selector types)")
        
        for item in items:
            try:
                # Get ASIN
                asin = item.attributes.get('data-asin', '')
                if not asin:
                    continue
                
                # Get title
                title_elem = item.css_first('h2 a span, .a-text-normal')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get URL
                link_elem = item.css_first('h2 a')
                url = ""
                if link_elem:
                    href = link_elem.attributes.get('href', '')
                    url = urljoin(self.base_url, href)
                
                # Get current price
                price_elem = item.css_first('.a-price .a-offscreen, .a-price-whole')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original/strikethrough price
                orig_price_elem = item.css_first('.a-price[data-a-strike="true"] .a-offscreen, .a-text-price .a-offscreen')
                original_price = None
                if orig_price_elem:
                    original_price = self.parse_price(orig_price_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.s-image')
                image_url = img_elem.attributes.get('src') if img_elem else None
                
                if asin and title:
                    products.append(DiscoveredProduct(
                        sku=asin,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Amazon item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('.s-pagination-next:not(.s-pagination-disabled)')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class WalmartCategoryParser(BaseCategoryParser):
    """Parser for Walmart category pages."""
    
    store_name = "walmart"
    base_url = "https://www.walmart.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Walmart product items
        items = parser.css('[data-item-id], [data-product-id]')
        
        for item in items:
            try:
                # Get product ID
                sku = item.attributes.get('data-item-id') or item.attributes.get('data-product-id', '')
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('[data-automation-id="product-title"], .sans-serif')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get URL
                link_elem = item.css_first('a[link-identifier]')
                url = ""
                if link_elem:
                    href = link_elem.attributes.get('href', '')
                    url = urljoin(self.base_url, href)
                
                # Get current price
                price_elem = item.css_first('[data-automation-id="product-price"] .f2, .f1')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price (was price)
                orig_elem = item.css_first('.strike, .was-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Walmart item: {e}")
                continue
        
        return products


class BestBuyCategoryParser(BaseCategoryParser):
    """Parser for Best Buy category pages."""
    
    store_name = "bestbuy"
    base_url = "https://www.bestbuy.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('.sku-item, [data-sku-id]')
        
        for item in items:
            try:
                # Get SKU
                sku = item.attributes.get('data-sku-id', '')
                if not sku:
                    sku_elem = item.css_first('.sku-value')
                    sku = sku_elem.text(strip=True) if sku_elem else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('.sku-title a, .sku-header a')
                title = title_elem.text(strip=True) if title_elem else ''
                url = ""
                if title_elem:
                    href = title_elem.attributes.get('href', '')
                    url = urljoin(self.base_url, href)
                
                # Get current price
                price_elem = item.css_first('.priceView-customer-price span, .pricing-price__regular-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price
                orig_elem = item.css_first('.pricing-price__regular-price-strikethrough, .pricing-price__was-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Best Buy item: {e}")
                continue
        
        return products


class TargetCategoryParser(BaseCategoryParser):
    """Parser for Target category pages."""
    
    store_name = "target"
    base_url = "https://www.target.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('[data-test="product-grid"] > li, .ProductCardWrapper')
        
        for item in items:
            try:
                # Get product link and extract TCIN
                link_elem = item.css_first('a[href*="/p/"]')
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Extract TCIN from URL
                tcin_match = re.search(r'/A-(\d+)', href)
                sku = tcin_match.group(1) if tcin_match else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('[data-test="product-title"], .ProductCardTitle')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get current price
                price_elem = item.css_first('[data-test="current-price"], .ProductCardPrice')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price
                orig_elem = item.css_first('[data-test="comparison-price"]')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Target item: {e}")
                continue
        
        return products


class CostcoCategoryParser(BaseCategoryParser):
    """Parser for Costco category pages."""
    
    store_name = "costco"
    base_url = "https://www.costco.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('.product-tile, .product')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a.product-tile-link, a[href*=".product."]')
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Extract product ID from URL
                sku_match = re.search(r'\.product\.(\d+)\.html', href)
                sku = sku_match.group(1) if sku_match else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('.description, .product-title')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get price
                price_elem = item.css_first('.price, .your-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Costco item: {e}")
                continue
        
        return products


class MacysCategoryParser(BaseCategoryParser):
    """Parser for Macy's category pages."""
    
    store_name = "macys"
    base_url = "https://www.macys.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('.productThumbnail, .product-thumbnail')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[href*="/product/"]')
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Extract product ID
                sku_match = re.search(r'/product/(\d+)', href)
                sku = sku_match.group(1) if sku_match else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('.productDescription, .product-description')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get current price
                price_elem = item.css_first('.prices .price, .sale-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price
                orig_elem = item.css_first('.prices .regular, .orig-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Macy's item: {e}")
                continue
        
        return products


class HomeDepotCategoryParser(BaseCategoryParser):
    """Parser for Home Depot category pages."""
    
    store_name = "homedepot"
    base_url = "https://www.homedepot.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('.browse-search__pod, [data-component="ProductPod"]')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[href*="/p/"]')
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Extract product ID (format: /p/TITLE/SKUID)
                sku_match = re.search(r'/p/[^/]+/(\d+)', href)
                sku = sku_match.group(1) if sku_match else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('.product-header__title, .pod-plp__description')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get current price
                price_elem = item.css_first('.price-format__main-price, [data-automation-id="main-price"]')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price
                orig_elem = item.css_first('.price-format__strike-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Home Depot item: {e}")
                continue
        
        return products


class LowesCategoryParser(BaseCategoryParser):
    """Parser for Lowe's category pages."""
    
    store_name = "lowes"
    base_url = "https://www.lowes.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        items = parser.css('[data-selector="splp-prd-image-container"], .product-card')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[href*="/pd/"]')
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Extract product ID
                sku_match = re.search(r'/(\d{7,})', href)
                sku = sku_match.group(1) if sku_match else ''
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('.description, [data-selector="product-title"]')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Get current price
                price_elem = item.css_first('[data-selector="price-value"], .art-pd-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price
                orig_elem = item.css_first('.was-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Lowe's item: {e}")
                continue
        
        return products


class eBayCategoryParser(BaseCategoryParser):
    """Parser for eBay deals pages (Buy It Now only)."""
    
    store_name = "ebay"
    base_url = "https://www.ebay.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # eBay deals page items - focus on daily deals
        items = parser.css('[data-testid="item-card"], .deal-item, .item-tile')
        
        # Also try general listing items
        if not items:
            items = parser.css('.s-item, [data-itemid]')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[data-testid="item-link"], a.item-link')
                if not link_elem:
                    link_elem = item.css_first('a.s-item__link, a[href*="/itm/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = href if href.startswith('http') else urljoin(self.base_url, href)
                
                # Get title
                title_elem = item.css_first('[data-testid="item-title"], .item-title, .s-item__title')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Skip auction items
                auction_elem = item.css_first('.s-item__bids, [data-testid="auction"]')
                if auction_elem:
                    continue
                
                # Extract item ID from URL
                sku = ''
                sku_match = re.search(r'/itm/(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                else:
                    # Try data-itemid
                    sku = item.attributes.get('data-itemid', '')
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('[data-testid="item-price"], .deal-price, .s-item__price')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('[data-testid="was-price"], .was-price, .STRIKETHROUGH')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.s-item__image-img, img[data-testid="item-image"]')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse eBay item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        # eBay deals pages don't typically have pagination
        # but search results do
        next_link = parser.css_first('.pagination__next, a[aria-label="Next page"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return href if href.startswith('http') else urljoin(self.base_url, href)
        return None


class OfficeDepotCategoryParser(BaseCategoryParser):
    """Parser for Office Depot category pages."""
    
    store_name = "officedepot"
    base_url = "https://www.officedepot.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Office Depot product items
        items = parser.css('.product_listing_container .product, .product-tile, [data-sku]')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a.product_nameLink, a.product-title')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/products/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                title = link_elem.text(strip=True)
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'/products/(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                else:
                    # Try data-sku
                    sku = item.attributes.get('data-sku', '')
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('.price_column .price, .sale-price, .final-price')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('.price_column .was-price, .original-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.product_image, img.product-image')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Office Depot item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('.pagination a.next, a[aria-label="Next"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class KohlsCategoryParser(BaseCategoryParser):
    """Parser for Kohl's category pages."""
    
    store_name = "kohls"
    base_url = "https://www.kohls.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Kohl's product items
        items = parser.css('.products-container .product, .product-tile, [data-webid]')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a.prod_image_link, a.product-link')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/product/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Get title
                title_elem = item.css_first('.prod_nameBlock a, .product-title')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'prd-(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                else:
                    # Try data-webid
                    sku = item.attributes.get('data-webid', '')
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('.prod_price_amount, .sale-price, .final-price')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('.prod_price_original, .was-price, .original-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.prod_image, img.product-image')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Kohl's item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('.pagination a.next, a[aria-label="Next Page"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class BHPhotoVideoCategoryParser(BaseCategoryParser):
    """Parser for B&H Photo Video category pages."""
    
    store_name = "bhphotovideo"
    base_url = "https://www.bhphotovideo.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # B&H product items
        items = parser.css('[data-selenium="miniProductPage"], .product-item, .item-tile')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[data-selenium="productTitle"], a.productTitle')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/c/product/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                title = link_elem.text(strip=True)
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'/c/product/(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('[data-selenium="pricingPrice"], .price_0, .finalPrice')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('[data-selenium="wasPrice"], .wasPrice, .listPrice')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img[data-selenium="productImage"], img.productImage')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse B&H Photo Video item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('a[data-selenium="pageNext"], a.next-page')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class GameStopCategoryParser(BaseCategoryParser):
    """Parser for GameStop category pages."""
    
    store_name = "gamestop"
    base_url = "https://www.gamestop.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # GameStop product items
        items = parser.css('.product-tile, [data-testid="product-tile"], .product-card')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a.product-tile-link, a[data-testid="product-link"]')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/products/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Get title
                title_elem = item.css_first('.product-tile-title, [data-testid="product-title"], .product-name')
                title = title_elem.text(strip=True) if title_elem else ''
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'/products/([a-zA-Z0-9-]+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('.actual-price, [data-testid="actual-price"], .sale-price')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('.regular-price, [data-testid="regular-price"], .strike-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.product-image, img[data-testid="product-image"]')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse GameStop item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('.page-next a, a[data-testid="next-page"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class MicroCenterCategoryParser(BaseCategoryParser):
    """Parser for Micro Center category pages."""
    
    store_name = "microcenter"
    base_url = "https://www.microcenter.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Micro Center product items
        items = parser.css('.product_wrapper, [data-id], .product-row')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a[data-name], a.productClickItemV2')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/product/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                title = link_elem.attributes.get('data-name', '') or link_elem.text(strip=True)
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'/product/(\d+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                else:
                    # Try data-id attribute
                    sku = item.attributes.get('data-id', '')
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('.price, .inStorePrice, [itemprop="price"]')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original price
                orig_elem = item.css_first('.previous-price, .was-price')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.ProductImage, img.lazy-load')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Micro Center item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        next_link = parser.css_first('.pages a.next, a.next-page')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class NeweggCategoryParser(BaseCategoryParser):
    """Parser for Newegg category and deals pages."""
    
    store_name = "newegg"
    base_url = "https://www.newegg.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Newegg product items - try multiple selectors
        items = parser.css('.item-cell, .item-container, [data-dealpromoid]')
        
        # Also try deal page format
        if not items:
            items = parser.css('.item-action, .product-item')
        
        for item in items:
            try:
                # Get product link
                link_elem = item.css_first('a.item-title, a[title]')
                if not link_elem:
                    link_elem = item.css_first('a[href*="/p/"], a[href*="/Product/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                title = link_elem.attributes.get('title', '') or link_elem.text(strip=True)
                
                # Extract product ID from URL
                sku = ''
                sku_match = re.search(r'/p/([A-Za-z0-9-]+)', href)
                if sku_match:
                    sku = sku_match.group(1)
                else:
                    # Try N82E format
                    sku_match = re.search(r'Item=([A-Za-z0-9-]+)', href)
                    if sku_match:
                        sku = sku_match.group(1)
                
                if not sku:
                    continue
                
                # Get current price
                price_elem = item.css_first('.price-current, .price-main .price-current, .price-current strong')
                current_price = None
                if price_elem:
                    price_text = price_elem.text(strip=True)
                    current_price = self.parse_price(price_text)
                
                # Get original/was price
                orig_elem = item.css_first('.price-was, .price-was-data')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img.item-img, img.lazy-img')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                if sku and title:
                    products.append(DiscoveredProduct(
                        sku=sku,
                        title=title[:200],
                        url=url,
                        current_price=current_price,
                        original_price=original_price,
                        store=self.store_name,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.debug(f"Failed to parse Newegg item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        # Find next page link
        next_link = parser.css_first('.btn-group-cell a[title="Next"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        
        # Alternative pagination
        next_link = parser.css_first('.list-tool-pagination .btn-page:not(.disabled) a[aria-label="Next"]')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        
        return None


# Registry of category parsers
CATEGORY_PARSERS = {
    "amazon_us": AmazonCategoryParser(),
    "walmart": WalmartCategoryParser(),
    "bestbuy": BestBuyCategoryParser(),
    "target": TargetCategoryParser(),
    "costco": CostcoCategoryParser(),
    "macys": MacysCategoryParser(),
    "homedepot": HomeDepotCategoryParser(),
    "lowes": LowesCategoryParser(),
    "newegg": NeweggCategoryParser(),
    "microcenter": MicroCenterCategoryParser(),
    "gamestop": GameStopCategoryParser(),
    "bhphotovideo": BHPhotoVideoCategoryParser(),
    "kohls": KohlsCategoryParser(),
    "officedepot": OfficeDepotCategoryParser(),
    "ebay": eBayCategoryParser(),
}


class CategoryScanner:
    """Scans store category pages to discover products."""
    
    def __init__(self):
        self._http_client = None
    
    async def _get_client(self, proxy: Optional[ProxyInfo] = None):
        """Get HTTP client with optional proxy and rotated headers."""
        import httpx
        
        # Rotate user agent
        user_agent = random.choice(USER_AGENTS)
        
        # More browser-like headers
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        
        if proxy:
            return httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=headers,
                proxy=proxy.url,
            )
        
        return httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        )
    
    async def scan_category(
        self,
        store: str,
        category_url: str,
        max_pages: int = 3,
    ) -> List[DiscoveredProduct]:
        """
        Scan a category page and discover products.
        
        Args:
            store: Store identifier
            category_url: Full category URL
            max_pages: Maximum pages to scan
            
        Returns:
            List of discovered products
        """
        if store not in CATEGORY_PARSERS:
            logger.error(f"No parser for store: {store}")
            return []
        
        parser = CATEGORY_PARSERS[store]
        all_products = []
        current_url = category_url
        pages_scanned = 0
        pages_successful = 0
        last_error: Optional[str] = None
        blocked_reason: Optional[str] = None
        
        while current_url and pages_scanned < max_pages:
            max_retries = 3
            retry_count = 0
            page_success = False
            
            while retry_count < max_retries and not page_success:
                proxy = None
                try:
                    # Get proxy if available
                    if proxy_rotator.has_proxies():
                        proxy = await proxy_rotator.get_next_proxy()
                    
                    # Rate limit
                    domain = urlparse(current_url).netloc
                    await rate_limiter.acquire_with_interval(domain, 10, 20, 5)
                    
                    # Fetch page with retry logic
                    client = await self._get_client(proxy)
                    try:
                        response = await client.get(current_url)
                        
                        # Check for specific HTTP errors that should trigger retry
                        if response.status_code == 403:
                            logger.warning(f"403 Forbidden for {store} page {pages_scanned + 1} (attempt {retry_count + 1}/{max_retries})")
                            if retry_count < max_retries - 1:
                                retry_count += 1
                                wait_time = (2 ** retry_count) * 5 + random.uniform(0, 3)
                                logger.debug(f"Retrying in {wait_time:.1f}s...")
                                await asyncio.sleep(wait_time)
                                if proxy:
                                    await proxy_rotator.report_failure(proxy.id)
                                    proxy = None  # Try different proxy next time
                                await client.aclose()
                                continue
                            else:
                                logger.error(f"Failed to access {store} after {max_retries} attempts (403 Forbidden)")
                                last_error = "HTTP 403 Forbidden"
                                await client.aclose()
                                response.raise_for_status()
                        
                        if response.status_code == 503:
                            logger.warning(f"503 Service Unavailable for {store} page {pages_scanned + 1} (attempt {retry_count + 1}/{max_retries})")
                            if retry_count < max_retries - 1:
                                retry_count += 1
                                wait_time = (2 ** retry_count) * 10 + random.uniform(0, 5)
                                logger.debug(f"Retrying in {wait_time:.1f}s...")
                                await asyncio.sleep(wait_time)
                                await client.aclose()
                                continue
                            else:
                                logger.error(f"Failed to access {store} after {max_retries} attempts (503 Service Unavailable)")
                                last_error = "HTTP 503 Service Unavailable"
                                await client.aclose()
                                response.raise_for_status()
                        
                        # For other status codes, raise immediately
                        response.raise_for_status()
                        html = response.text
                        page_success = True
                        await client.aclose()
                        
                    except httpx.HTTPStatusError as e:
                        status_code = e.response.status_code
                        reason = e.response.reason_phrase or "HTTP error"
                        await client.aclose()
                        
                        if status_code in (403, 503) and retry_count < max_retries - 1:
                            retry_count += 1
                            wait_time = (2 ** retry_count) * (10 if status_code == 503 else 5) + random.uniform(0, 5)
                            logger.warning(f"HTTP {status_code} error for {store}, retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            if proxy:
                                await proxy_rotator.report_failure(proxy.id)
                                proxy = None
                            continue
                        else:
                            last_error = f"HTTP {status_code} {reason}"
                            logger.error(f"HTTP {status_code} error for {store} category: {e}")
                            if proxy:
                                await proxy_rotator.report_failure(proxy.id)
                            break
                    except Exception as e:
                        await client.aclose()
                        raise
                    
                    # Report proxy success
                    if proxy:
                        await proxy_rotator.report_success(proxy.id)
                    
                    # Parse products
                    products = parser.parse_category_page(html, current_url)
                    all_products.extend(products)
                    
                    logger.info(f"Scanned {store} page {pages_scanned + 1}: found {len(products)} products")
                    pages_successful += 1

                    if not products:
                        possible_block = detect_block_reason(html)
                        if possible_block:
                            blocked_reason = blocked_reason or possible_block
                            logger.warning(
                                f"No products parsed for {store} page {pages_scanned + 1}: possible block ({possible_block})"
                            )
                        else:
                            logger.debug(
                                f"No products parsed for {store} page {pages_scanned + 1}; selectors may be stale"
                            )
                    
                    # Get next page
                    current_url = parser.get_next_page_url(html, current_url)
                    pages_scanned += 1
                    
                    # Small delay between pages
                    await asyncio.sleep(random.uniform(2, 5))
                    
                except Exception as e:
                    error_type = type(e).__name__
                    # If this wasn't handled by the inner try/except, handle it here
                    if isinstance(e, httpx.HTTPStatusError):
                        status_code = e.response.status_code
                        reason = e.response.reason_phrase or "HTTP error"
                        if status_code in (403, 503) and retry_count < max_retries - 1:
                            retry_count += 1
                            wait_time = (2 ** retry_count) * (10 if status_code == 503 else 5) + random.uniform(0, 5)
                            logger.warning(f"HTTP {status_code} error for {store}, retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            if proxy:
                                await proxy_rotator.report_failure(proxy.id)
                                proxy = None
                            continue
                        else:
                            last_error = f"HTTP {status_code} {reason}"
                            logger.error(f"HTTP {status_code} error for {store} category: {e}")
                            if proxy:
                                await proxy_rotator.report_failure(proxy.id)
                            # Give up on this page, try next category
                            break
                    else:
                        # Other errors - log and continue to next page if possible
                        last_error = f"{error_type}: {e}" if str(e) else error_type
                        logger.error(f"Failed to scan {store} category page {pages_scanned + 1}: {error_type}: {e}")
                        if proxy:
                            await proxy_rotator.report_failure(proxy.id)
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            wait_time = (2 ** retry_count) * 3 + random.uniform(0, 2)
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            # Give up on this page
                            break
            
            # If we exhausted retries, skip to next category
            if not page_success:
                logger.warning(f"Skipping remaining pages for {store} after failed retries")
                break
        
        if pages_successful == 0:
            error_message = last_error or "No pages successfully scanned"
            logger.error(f"Category scan failed for {store}: {error_message}")
            raise CategoryScanError(store, category_url, error_message)
        
        if len(all_products) == 0 and blocked_reason:
            error_message = f"Blocked or bot challenge detected: {blocked_reason}"
            logger.error(f"Category scan failed for {store}: {error_message}")
            raise CategoryScanError(store, category_url, error_message)
        
        if len(all_products) == 0 and not blocked_reason:
            logger.warning(
                f"No products parsed for {store} (url: {category_url}). Selectors may be stale or page is JS-rendered."
            )
        
        logger.info(f"Category scan complete: {len(all_products)} products from {store}")
        return all_products


# Global scanner instance
category_scanner = CategoryScanner()
