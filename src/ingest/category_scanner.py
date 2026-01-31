"""Category scanner for discovering products from store category pages."""

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Optional, List
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from src.ingest.proxy_manager import proxy_rotator, ProxyInfo
from src.ingest.rate_limiter import rate_limiter
from src.ingest.content_analyzer import content_analyzer
from src.ingest.http_cache import http_cache
from src.ingest.store_health import store_health
from src.config import settings
from src import metrics

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
            except InvalidOperation as exc:
                logger.debug("Failed to parse price: %s", price_text, exc_info=exc)
                return None
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
            logger.debug("No product items found on Amazon page (checked 3 selector types)")
        
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


class SaveYourDealsCategoryParser(BaseCategoryParser):
    """Parser for SaveYourDeals.com - Amazon affiliate deal aggregator."""
    
    store_name = "saveyourdeals"
    base_url = "https://saveyourdeals.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # SaveYourDeals uses product cards with Amazon affiliate links
        # Try multiple selectors for deal cards
        items = parser.css('[class*="deal"], [class*="product"], article, .card')
        
        # If no items, try looking for links to Amazon
        if not items:
            items = parser.css('a[href*="amazon.com"]')
            # Wrap each link in a container-like context
            items = [link.parent for link in items if link.parent]
        
        for item in items:
            try:
                # Get Amazon link to extract ASIN
                amazon_link = item.css_first('a[href*="amazon.com"]')
                if not amazon_link:
                    continue
                
                href = amazon_link.attributes.get('href', '')
                
                # Extract ASIN from Amazon URL
                sku = ''
                # Match /dp/ASIN or /product/ASIN patterns
                asin_match = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', href)
                if asin_match:
                    sku = asin_match.group(1)
                else:
                    # Try ASIN in query string
                    asin_match = re.search(r'[?&]asin=([A-Z0-9]{10})', href, re.IGNORECASE)
                    if asin_match:
                        sku = asin_match.group(1)
                
                if not sku:
                    continue
                
                # Get title
                title_elem = item.css_first('h2, h3, h4, .title, [class*="title"], [class*="name"]')
                title = title_elem.text(strip=True) if title_elem else ''
                
                if not title:
                    title = amazon_link.text(strip=True)
                
                if not title or len(title) < 5:
                    continue
                
                # Get current price
                price_elem = item.css_first('[class*="price"]:not([class*="original"]):not([class*="was"]), .sale-price, .deal-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original/was price
                orig_elem = item.css_first('[class*="original"], [class*="was"], [class*="list"], .strike, s, del')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                # Use the Amazon URL as the product URL
                url = href if href.startswith('http') else f"https://www.amazon.com/dp/{sku}"
                
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
                logger.debug(f"Failed to parse SaveYourDeals item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        # Look for pagination links
        next_link = parser.css_first('a[rel="next"], a.next, [class*="next"] a, .pagination a:contains("Next")')
        if next_link:
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class SlickdealsCategoryParser(BaseCategoryParser):
    """Parser for Slickdeals.net - Community-curated deal aggregator."""
    
    store_name = "slickdeals"
    base_url = "https://slickdeals.net"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Slickdeals frontpage deals
        items = parser.css('[class*="dealCard"], [class*="deal-card"], [data-deal-id], .fpDeal, .dealRow')
        
        # Fallback to generic deal containers
        if not items:
            items = parser.css('.bp-p-dealCard, article[class*="deal"], [class*="fpGrid"] > div')
        
        for item in items:
            try:
                # Get deal link
                link_elem = item.css_first('a[href*="/f/"], a[href*="/e/"], a.dealTitle, [class*="title"] a')
                if not link_elem:
                    link_elem = item.css_first('a[href*="slickdeals.net"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                title = link_elem.text(strip=True)
                
                if not title:
                    title_elem = item.css_first('[class*="title"], h2, h3')
                    title = title_elem.text(strip=True) if title_elem else ''
                
                if not title or len(title) < 5:
                    continue
                
                # Extract deal ID as SKU
                sku = ''
                deal_id = item.attributes.get('data-deal-id', '')
                if deal_id:
                    sku = f"sd-{deal_id}"
                else:
                    # Extract from URL
                    id_match = re.search(r'/(?:f|e)/(\d+)', href)
                    if id_match:
                        sku = f"sd-{id_match.group(1)}"
                    else:
                        # Use hash of URL as fallback
                        import hashlib
                        sku = f"sd-{hashlib.md5(href.encode()).hexdigest()[:10]}"
                
                # Get price - Slickdeals shows deal prices
                price_elem = item.css_first('[class*="price"], .dealPrice, .bp-p-dealCard_price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get original price if shown
                orig_elem = item.css_first('[class*="original"], [class*="list"], .strike, s, del')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get vote count for confidence scoring
                vote_elem = item.css_first('[class*="vote"], [class*="score"], .dealScore')
                # We don't use confidence directly but could enhance later
                
                # Get image
                img_elem = item.css_first('img[class*="deal"], img.fpImage, img')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                
                # Get store/merchant if available
                store_elem = item.css_first('[class*="store"], [class*="merchant"], .storeName')
                # Could be used for filtering/categorization later
                
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
                logger.debug(f"Failed to parse Slickdeals item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        parser = HTMLParser(html)
        # Slickdeals pagination
        next_link = parser.css_first('a.page-next, a[rel="next"], .pagination a:last-child')
        if next_link and 'disabled' not in next_link.attributes.get('class', ''):
            href = next_link.attributes.get('href', '')
            return urljoin(self.base_url, href)
        return None


class WootCategoryParser(BaseCategoryParser):
    """Parser for Woot.com - Amazon-owned deal site with limited-time offers."""
    
    store_name = "woot"
    base_url = "https://www.woot.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        products = []
        parser = HTMLParser(html)
        
        # Woot deal items - try multiple selectors
        items = parser.css('[class*="deal"], [class*="event"], [class*="product"], article')
        
        # Also try section-based layout
        if not items:
            items = parser.css('.woot-deal, .sale-thumb, [data-eventid]')
        
        for item in items:
            try:
                # Get deal link
                link_elem = item.css_first('a[href*="/offers/"], a[href*="/events/"], a.dealLink')
                if not link_elem:
                    link_elem = item.css_first('a[href^="/"]')
                
                if not link_elem:
                    continue
                
                href = link_elem.attributes.get('href', '')
                url = urljoin(self.base_url, href)
                
                # Get title
                title_elem = item.css_first('h2, h3, [class*="title"], [class*="name"]')
                title = title_elem.text(strip=True) if title_elem else ''
                
                if not title:
                    title = link_elem.text(strip=True)
                
                if not title or len(title) < 5:
                    continue
                
                # Extract event/offer ID as SKU
                sku = ''
                event_id = item.attributes.get('data-eventid', '')
                if event_id:
                    sku = f"woot-{event_id}"
                else:
                    # Extract from URL
                    id_match = re.search(r'/(?:offers|events)/([a-zA-Z0-9-]+)', href)
                    if id_match:
                        sku = f"woot-{id_match.group(1)}"
                    else:
                        # Use hash as fallback
                        import hashlib
                        sku = f"woot-{hashlib.md5(href.encode()).hexdigest()[:10]}"
                
                # Get current sale price
                price_elem = item.css_first('[class*="price"]:not([class*="list"]), .sale-price, .current-price')
                current_price = None
                if price_elem:
                    current_price = self.parse_price(price_elem.text(strip=True))
                
                # Get list/original price
                orig_elem = item.css_first('[class*="list"], [class*="msrp"], [class*="was"], .strike, s')
                original_price = None
                if orig_elem:
                    original_price = self.parse_price(orig_elem.text(strip=True))
                
                # Get image
                img_elem = item.css_first('img')
                image_url = None
                if img_elem:
                    image_url = img_elem.attributes.get('src') or img_elem.attributes.get('data-src')
                    # Woot sometimes uses lazy loading
                    if not image_url:
                        image_url = img_elem.attributes.get('data-lazy-src')
                
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
                logger.debug(f"Failed to parse Woot item: {e}")
                continue
        
        return products
    
    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        # Woot typically doesn't have pagination on main deal pages
        # Deals are time-limited and all shown on one page
        parser = HTMLParser(html)
        next_link = parser.css_first('a[rel="next"], a.next-page, .pagination a.next')
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
    "saveyourdeals": SaveYourDealsCategoryParser(),
    "slickdeals": SlickdealsCategoryParser(),
    "woot": WootCategoryParser(),
}


class CategoryScanner:
    """Scans store category pages to discover products."""
    
    def __init__(self):
        self._http_clients: dict[str, httpx.AsyncClient] = {}  # domain -> client
        self._client_locks: dict[str, asyncio.Lock] = {}  # domain -> lock for client creation
        self._client_locks_lock = asyncio.Lock()  # Lock for creating domain locks
        self._warmup_done = False
    
    async def warmup_connections(self, domains: Optional[List[str]] = None):
        """
        Warm up HTTP connections for common domains.
        
        Args:
            domains: List of domains to warm up (defaults to common store domains)
        """
        if not settings.connection_pool_warmup:
            return
        
        if self._warmup_done:
            return
        
        if domains is None:
            # Common store domains
            domains = [
                "www.amazon.com",
                "www.walmart.com",
                "www.target.com",
                "www.bestbuy.com",
                "www.costco.com",
                "www.homedepot.com",
                "www.lowes.com",
                "www.newegg.com",
            ]
        
        logger.info(f"Warming up connections for {len(domains)} domains")
        
        # Create clients for each domain (this establishes connection pools)
        for domain in domains:
            try:
                # Get a client for this domain (will create if not exists)
                await self._get_client(domain)
                # Make a lightweight HEAD request to establish connection
                client = await self._get_client(domain)
                try:
                    await client.head(f"https://{domain}", timeout=5.0)
                except Exception:
                    pass  # Ignore errors, we just want to establish the connection
            except Exception as e:
                logger.debug(f"Failed to warmup {domain}: {e}")
        
        self._warmup_done = True
        logger.info("Connection warmup complete")
    
    async def _get_client(
        self, 
        domain: str, 
        proxy: Optional[ProxyInfo] = None,
        user_agent: Optional[str] = None,
        read_timeout: Optional[float] = None
    ):
        """
        Get HTTP client with optional proxy and rotated headers.
        Reuses clients per domain for connection pooling.
        
        Args:
            domain: Domain name (e.g., 'www.amazon.com')
            proxy: Optional proxy info
            user_agent: Optional user agent string (if None, rotates randomly)
            read_timeout: Optional read timeout override (if None, uses default)
            
        Returns:
            httpx.AsyncClient instance
        """
        # Create lock for this domain if needed (with shared lock to avoid race)
        async with self._client_locks_lock:
            if domain not in self._client_locks:
                self._client_locks[domain] = asyncio.Lock()
        
        # Track if user_agent was None for cache key generation
        user_agent_was_none = user_agent is None
        
        # Use user agent if provided, otherwise rotate
        if user_agent is None:
            user_agent = random.choice(USER_AGENTS)
        
        # Use structured timeout
        if read_timeout is None:
            read_timeout = settings.category_request_timeout
        
        timeout = httpx.Timeout(
            connect=10.0,      # Connection timeout
            read=read_timeout, # Read timeout
            write=10.0,        # Write timeout
            pool=5.0           # Pool timeout
        )
        
        # Use existing client if available and no proxy/user_agent/timeout change
        # When user_agent was None, use fixed placeholder in cache key to allow reuse
        user_agent_for_key = "rotating" if user_agent_was_none else user_agent
        client_key = f"{domain}:{proxy.id if proxy else 'direct'}:{user_agent_for_key}:{read_timeout}"
        if client_key in self._http_clients:
            return self._http_clients[client_key]
        
        # Create new client with lock to avoid race conditions
        async with self._client_locks[domain]:
            # Double-check after acquiring lock
            if client_key in self._http_clients:
                return self._http_clients[client_key]
            
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
            
            # Create client with optimized connection pooling
            limits = httpx.Limits(
                max_keepalive_connections=settings.connection_keepalive,
                max_connections=settings.http_max_connections,
            )
            
            if proxy:
                client = httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=headers,
                    proxy=proxy.url,
                    limits=limits,
                )
            else:
                client = httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=headers,
                    limits=limits,
                )
            
            self._http_clients[client_key] = client
            return client
    
    async def close(self):
        """Close all HTTP clients."""
        for client_key, client in self._http_clients.items():
            try:
                await client.aclose()
            except Exception as e:
                # Log client close failures with context
                logger.debug(
                    f"Failed to close HTTP client {client_key}: {e}",
                    exc_info=True
                )
        self._http_clients.clear()
        self._client_locks.clear()
    
    async def _scan_single_page(
        self,
        store: str,
        parser: BaseCategoryParser,
        url: str,
        page_num: int,
    ) -> tuple[bool, List[DiscoveredProduct], Optional[str], Optional[str], Optional[str]]:
        """
        Scan a single page and return products.
        
        Returns:
            (success, products, error, blocked_reason, html)
        """
        max_retries = 3
        retry_count = 0
        last_error: Optional[str] = None
        blocked_reason: Optional[str] = None
        used_proxies: set[int] = set()
        current_user_agent: Optional[str] = None
        read_timeout: float = settings.category_request_timeout
        has_timeout_error: bool = False
        
        domain = urlparse(url).netloc
        
        while retry_count < max_retries:
            proxy = None
            try:
                # Get proxy if available, excluding already-tried proxies
                if proxy_rotator.has_proxies():
                    proxy = await proxy_rotator.get_next_proxy(exclude_ids=used_proxies if used_proxies else None)
                    if proxy:
                        logger.debug(
                            f"Using proxy {proxy.host}:{proxy.port} for {store} page {page_num} "
                            f"(attempt {retry_count + 1}/{max_retries})"
                        )
                
                # Rotate user agent on each retry
                current_user_agent = random.choice(USER_AGENTS)
                
                # Increase timeout if we had a timeout error
                if has_timeout_error:
                    read_timeout = 90.0  # Use longer timeout for retries after timeout
                    logger.debug(f"Increased read timeout to {read_timeout}s for {store} after timeout error")
                
                # Use adaptive rate limiting if enabled
                if settings.adaptive_rate_limiting_enabled:
                    await rate_limiter.acquire_adaptive(store)
                else:
                await rate_limiter.acquire_with_interval(domain, 10, 20, 5)
                
                # Track request timing for store health
                request_start_time = time.monotonic()
                
                # Get conditional headers for caching
                conditional_headers = await http_cache.get_conditional_headers(url)
                
                # Fetch page with retry logic
                client = await self._get_client(domain, proxy, user_agent=current_user_agent, read_timeout=read_timeout)
                try:
                    response = await client.get(url, headers=conditional_headers if conditional_headers else None)
                    
                    # Check for specific HTTP errors that should trigger retry
                    if response.status_code == 403:
                        proxy_info = f" (proxy: {proxy.host}:{proxy.port})" if proxy else " (no proxy)"
                        logger.warning(
                            f"403 Forbidden for {store} page {page_num} "
                            f"(attempt {retry_count + 1}/{max_retries}, "
                            f"UA: {current_user_agent[:50]}...){proxy_info}"
                        )
                        if proxy:
                            used_proxies.add(proxy.id)
                            await proxy_rotator.report_failure(proxy.id)
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            # Increased backoff for 403 errors
                            wait_time = (2 ** retry_count) * 15 + random.uniform(5, 15)
                            logger.debug(f"Retrying with different proxy and user agent in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            # Reset timeout for next attempt
                            read_timeout = settings.category_request_timeout
                            has_timeout_error = False
                            continue
                        else:
                            logger.error(
                                f"Failed to access {store} after {max_retries} attempts (403 Forbidden)"
                            )
                            last_error = "HTTP 403 Forbidden"
                            response.raise_for_status()
                    
                    if response.status_code == 503:
                        logger.warning(
                            f"503 Service Unavailable for {store} page {page_num} "
                            f"(attempt {retry_count + 1}/{max_retries})"
                        )
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            wait_time = (2 ** retry_count) * 10 + random.uniform(0, 5)
                            logger.debug(f"Retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            read_timeout = settings.category_request_timeout
                            has_timeout_error = False
                            continue
                        else:
                            logger.error(f"Failed to access {store} after {max_retries} attempts (503 Service Unavailable)")
                            last_error = "HTTP 503 Service Unavailable"
                            response.raise_for_status()

                    if response.status_code == 429:
                        logger.warning(
                            f"HTTP 429 Too Many Requests for {store} page {page_num} "
                            f"(attempt {retry_count + 1}/{max_retries})"
                        )
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            
                            # Try to read Retry-After header
                            retry_seconds = None
                            retry_after = response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    # Try parsing as numeric seconds first
                                    retry_seconds = float(retry_after)
                                except ValueError:
                                    try:
                                        # Try parsing as HTTP-date
                                        retry_date = parsedate_to_datetime(retry_after)
                                        now = datetime.now(timezone.utc)
                                        retry_seconds = (retry_date - now).total_seconds()
                                        if retry_seconds < 0:
                                            retry_seconds = None
                                    except (ValueError, TypeError):
                                        # Invalid format, will fall back to exponential backoff
                                        retry_seconds = None
                            
                            # Calculate exponential backoff fallback
                            backoff = (2 ** retry_count) * 8 + random.uniform(0, 5)
                            
                            # Use Retry-After if available, otherwise use backoff
                            # Take max of both to ensure we respect server's request
                            if retry_seconds is not None:
                                wait_time = max(retry_seconds, backoff)
                                logger.debug(f"Retry-After header: {retry_after}, parsed: {retry_seconds:.1f}s, using: {wait_time:.1f}s")
                            else:
                                wait_time = backoff
                                logger.debug(f"No valid Retry-After header, using exponential backoff: {wait_time:.1f}s")
                            
                            # Cap wait time to a reasonable maximum (5 minutes)
                            wait_time = min(wait_time, 300.0)
                            
                            logger.debug(f"Retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            read_timeout = settings.category_request_timeout
                            has_timeout_error = False
                            continue
                        else:
                            logger.error(f"Failed to access {store} after {max_retries} attempts (HTTP 429 Too Many Requests)")
                            last_error = "HTTP 429 Too Many Requests"
                            response.raise_for_status()
                    
                    if response.status_code in (500, 502, 504):
                        logger.warning(
                            f"HTTP {response.status_code} for {store} page {page_num} "
                            f"(attempt {retry_count + 1}/{max_retries})"
                        )
                        if retry_count < max_retries - 1:
                            retry_count += 1
                            wait_time = (2 ** retry_count) * 8 + random.uniform(0, 5)
                            logger.debug(f"Retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            read_timeout = settings.category_request_timeout
                            has_timeout_error = False
                            continue
                        else:
                            logger.error(f"Failed to access {store} after {max_retries} attempts (HTTP {response.status_code})")
                            last_error = f"HTTP {response.status_code} Server Error"
                            response.raise_for_status()
                    
                    # For other status codes, raise immediately
                    response.raise_for_status()
                    
                    # Calculate request duration for store health
                    request_duration_ms = (time.monotonic() - request_start_time) * 1000
                    
                    # Handle 304 Not Modified (cached content)
                    if response.status_code == 304:
                        cached_html = await http_cache.get_cached_content(url)
                        if cached_html:
                            metrics.record_cache_hit(store)
                            html = cached_html
                            logger.debug(f"Using cached content for {store} page {page_num} (304 Not Modified)")
                        else:
                            # Cache miss despite 304 - shouldn't happen but fetch fresh
                            logger.warning(f"304 response but no cached content for {url}")
                            metrics.record_cache_miss(store)
                            # Re-fetch without conditional headers
                            response = await client.get(url)
                    response.raise_for_status()
                    html = response.text
                    else:
                        html = response.text
                        metrics.record_cache_miss(store)
                        
                        # Store in cache if we got cache headers
                        etag = response.headers.get("ETag")
                        last_modified = response.headers.get("Last-Modified")
                        if etag or last_modified:
                            await http_cache.store(url, html, etag, last_modified, store)
                    
                except httpx.ReadTimeout as e:
                    # Handle ReadTimeout explicitly - increase timeout and try different proxy
                    has_timeout_error = True
                    request_duration_ms = (time.monotonic() - request_start_time) * 1000
                    proxy_info = f" (proxy: {proxy.host}:{proxy.port})" if proxy else " (no proxy)"
                    logger.warning(
                        f"ReadTimeout for {store} page {page_num} "
                        f"(attempt {retry_count + 1}/{max_retries}){proxy_info}"
                    )
                    # Record timeout in store health
                    await store_health.record_request(
                        store=store,
                        success=False,
                        duration_ms=request_duration_ms,
                        blocked=False,
                    )
                    if proxy:
                        used_proxies.add(proxy.id)
                        await proxy_rotator.report_failure(proxy.id)
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        # Short backoff for timeout - proxy might be slow
                        wait_time = (2 ** retry_count) * 3 + random.uniform(0, 2)
                        logger.debug(f"Retrying with longer timeout and different proxy in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        last_error = "ReadTimeout"
                        logger.error(f"Failed to scan {store} after {max_retries} attempts: ReadTimeout")
                        return (False, [], last_error, None, None)
                
                except httpx.ConnectError as e:
                    # Handle ConnectError explicitly - immediate proxy rotation, no backoff
                    request_duration_ms = (time.monotonic() - request_start_time) * 1000
                    proxy_info = f" (proxy: {proxy.host}:{proxy.port})" if proxy else " (no proxy)"
                    logger.warning(
                        f"ConnectError for {store} page {page_num} "
                        f"(attempt {retry_count + 1}/{max_retries}){proxy_info}: {e}"
                    )
                    # Record connection error in store health
                    await store_health.record_request(
                        store=store,
                        success=False,
                        duration_ms=request_duration_ms,
                        blocked=False,
                    )
                    if proxy:
                        used_proxies.add(proxy.id)
                        await proxy_rotator.report_failure(proxy.id)
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        # No backoff for ConnectError - try next proxy immediately
                        logger.debug("Immediately retrying with different proxy (no backoff for connection errors)...")
                        read_timeout = settings.category_request_timeout
                        has_timeout_error = False
                        continue
                    else:
                        last_error = "ConnectError: All connection attempts failed"
                        logger.error(f"Failed to scan {store} after {max_retries} attempts: ConnectError")
                        return (False, [], last_error, None, None)
                
                except httpx.HTTPStatusError as e:
                    status_code = e.response.status_code
                    reason = e.response.reason_phrase or "HTTP error"
                    request_duration_ms = (time.monotonic() - request_start_time) * 1000
                    
                    # Record HTTP error in store health
                    await store_health.record_request(
                        store=store,
                        success=False,
                        duration_ms=request_duration_ms,
                        status_code=status_code,
                        blocked=(status_code == 403),
                    )
                    
                    if status_code in (403, 429, 500, 502, 503, 504) and retry_count < max_retries - 1:
                        retry_count += 1
                        wait_time_base = 10 if status_code == 503 else 8
                        wait_time = (2 ** retry_count) * wait_time_base + random.uniform(0, 5)
                        proxy_info = f" (proxy: {proxy.host}:{proxy.port})" if proxy else ""
                        logger.warning(
                            f"HTTP {status_code} error for {store}{proxy_info}, retrying in {wait_time:.1f}s..."
                        )
                        if proxy and status_code == 403:
                            used_proxies.add(proxy.id)
                            await proxy_rotator.report_failure(proxy.id)
                        await asyncio.sleep(wait_time)
                        read_timeout = settings.category_request_timeout
                        has_timeout_error = False
                        continue
                    else:
                        last_error = f"HTTP {status_code} {reason}"
                        logger.exception(f"HTTP {status_code} error for {store} category: {e}")
                        return (False, [], last_error, None, None)
                
                # Report proxy success
                if proxy:
                    await proxy_rotator.report_success(proxy.id)
                
                # Record successful request to store health tracker
                await store_health.record_request(
                    store=store,
                    success=True,
                    duration_ms=request_duration_ms,
                    status_code=response.status_code,
                    blocked=False,
                )
                
                # Use content analyzer to check for blocks before parsing
                analysis = content_analyzer.analyze(html, store)
                if analysis.is_blocked:
                    blocked_reason = content_analyzer.get_block_type_label(analysis.block_type)
                    logger.warning(
                        f"Content analysis detected block for {store} page {page_num}: {blocked_reason}"
                    )
                    metrics.record_scan_block(store, analysis.block_type or "unknown")
                    
                    # Record block in store health
                    await store_health.record_request(
                        store=store,
                        success=False,
                        duration_ms=request_duration_ms,
                        blocked=True,
                        block_type=analysis.block_type,
                    )
                    
                    # Retry if we have attempts left
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        wait_time = (2 ** retry_count) * 15 + random.uniform(5, 15)
                        logger.debug(f"Retrying after detected block in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        return (False, [], f"Blocked or bot challenge detected", blocked_reason, html)
                
                # Parse products
                products = parser.parse_category_page(html, url)
                
                logger.info(
                    f"Scanned {store} page {page_num}: found {len(products)} products"
                    f"{' (proxy: ' + proxy.host + ':' + str(proxy.port) + ')' if proxy else ''}"
                )

                if not products:
                    possible_block = detect_block_reason(html)
                    if possible_block:
                        blocked_reason = possible_block
                        logger.warning(
                            f"No products parsed for {store} page {page_num}: possible block ({possible_block})"
                        )
                    else:
                        logger.debug(
                            f"No products parsed for {store} page {page_num}; selectors may be stale"
                        )
                
                return (True, products, None, blocked_reason, html)
                
            except Exception as e:
                error_type = type(e).__name__
                last_error = f"{error_type}: {e}" if str(e) else error_type
                proxy_info = f" (proxy: {proxy.host}:{proxy.port})" if proxy else ""
                logger.exception(
                    f"Failed to scan {store} category page {page_num}: {error_type}: {e}{proxy_info}"
                )
                if proxy:
                    used_proxies.add(proxy.id)
                    await proxy_rotator.report_failure(proxy.id)
                if retry_count < max_retries - 1:
                    retry_count += 1
                    wait_time = (2 ** retry_count) * 3 + random.uniform(0, 2)
                    await asyncio.sleep(wait_time)
                    read_timeout = settings.category_request_timeout
                    has_timeout_error = False
                    continue
                else:
                    return (False, [], last_error, None, None)
        
        return (False, [], last_error or "Max retries exceeded", blocked_reason, None)
    
    async def scan_category(
        self,
        store: str,
        category_url: str,
        max_pages: int = 3,
    ) -> List[DiscoveredProduct]:
        """
        Scan a category page and discover products.
        Supports parallel page scanning for improved performance.
        
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
        pages_successful = 0
        last_error: Optional[str] = None
        blocked_reason: Optional[str] = None
        
        # Use parallel page scanning if enabled (simplified approach)
        max_parallel_pages = getattr(settings, 'max_parallel_pages_per_category', 1)
        parallel_attempted = False
        
        if max_pages > 1 and max_parallel_pages > 1:
            parallel_attempted = True
            # Parallel page scanning: discover URLs first, then scan in parallel
            page_urls = [category_url]
            current_url = category_url
            first_page_html = None
            
            # Discover page URLs sequentially (needed for pagination)
            # Try to discover URLs, but if it fails, fall back to sequential
            try:
                domain = urlparse(current_url).netloc
                proxy = None
                if proxy_rotator.has_proxies():
                    proxy = await proxy_rotator.get_next_proxy()
                
                # Rate limit before first request
                await rate_limiter.acquire_with_interval(domain, 10, 20, 5)
                
                client = await self._get_client(domain, proxy)
                
                # Get first page to discover pagination
                response = await client.get(current_url)
                response.raise_for_status()
                first_page_html = response.text
                
                # Parse first page products to avoid re-fetching
                first_products = parser.parse_category_page(first_page_html, current_url)
                all_products.extend(first_products)
                pages_successful += 1
                
                # Discover remaining page URLs
                html = first_page_html
                while len(page_urls) < max_pages:
                    next_url = parser.get_next_page_url(html, current_url)
                    if not next_url:
                        break
                    page_urls.append(next_url)
                    current_url = next_url
                    
                    # Fetch next page to get its next URL (only if we need more)
                    if len(page_urls) < max_pages:
                        # Rate limit before fetching next page
                        await rate_limiter.acquire_with_interval(domain, 10, 20, 5)
                        response = await client.get(next_url)
                        response.raise_for_status()
                        html = response.text
            except Exception as e:
                logger.debug(f"Could not discover all page URLs upfront: {e}, falling back to sequential")
                # If discovery fails, fall through to sequential scanning below
                page_urls = [category_url]
            
            # If we discovered multiple pages, scan them in parallel
            if len(page_urls) > 1:
                # Dynamic concurrency based on site health
                effective_parallel = max_parallel_pages
                if settings.dynamic_concurrency:
                    # Adjust based on store health
                    domain = urlparse(category_url).netloc
                    health_summary = await store_health.get_health_summary(store)
                    error_rate = health_summary.get("error_rate", 0.0)
                    
                    # Reduce concurrency if site is struggling
                    if error_rate > 0.3:
                        effective_parallel = max(1, int(max_parallel_pages * 0.5))
                    elif error_rate > 0.1:
                        effective_parallel = max(2, int(max_parallel_pages * 0.75))
                
                semaphore = asyncio.Semaphore(effective_parallel)
                
                async def scan_page_with_semaphore(url: str, page_num: int):
                    async with semaphore:
                        # Configurable delay before scanning (except first page)
                        if page_num > 1:
                            delay = random.uniform(
                                settings.min_page_delay_seconds,
                                settings.max_page_delay_seconds
                            )
                            await asyncio.sleep(delay)
                        return await self._scan_single_page(store, parser, url, page_num)
                
                # Scan remaining pages in parallel (skip first page, already scanned)
                tasks = [
                    scan_page_with_semaphore(url, i + 1)
                    for i, url in enumerate(page_urls) if i > 0  # Skip first page
                ]
                
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results
                    for i, result in enumerate(results):
                        page_num = i + 2  # +2 because we skipped first page
                        if isinstance(result, Exception):
                            logger.error(f"Error scanning page {page_num}: {result}")
                            if not last_error:
                                last_error = str(result)
                            continue
                        
                        success, products, error, block, html = result
                        if success:
                            all_products.extend(products)
                            pages_successful += 1
                            if block and not blocked_reason:
                                blocked_reason = block
                        else:
                            if error and not last_error:
                                last_error = error
        
        # Sequential scanning (fallback when parallel is disabled, only one page, or parallel failed)
        if not parallel_attempted or pages_successful == 0:
            # Sequential scanning (fallback when parallel is disabled or only one page)
            current_url = category_url
            pages_scanned = 0
            
            while current_url and pages_scanned < max_pages:
                success, products, error, block, html = await self._scan_single_page(
                    store, parser, current_url, pages_scanned + 1
                )
                
                if success:
                    all_products.extend(products)
                    pages_successful += 1
                    if block and not blocked_reason:
                        blocked_reason = block
                    
                    # Get next page URL using the HTML from _scan_single_page
                    if html:
                        current_url = parser.get_next_page_url(html, current_url)
                        pages_scanned += 1
                        
                        # Configurable delay between pages
                        if current_url:
                            delay = random.uniform(
                                settings.min_page_delay_seconds,
                                settings.max_page_delay_seconds
                            )
                            await asyncio.sleep(delay)
                    else:
                        # No HTML available, can't get next page
                        logger.warning("No HTML available to determine next page URL")
                        break
                else:
                    if error:
                        last_error = error
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
