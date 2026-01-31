"""Lightweight HTML parser using lxml for fast price extraction.

Uses C-based lxml for significantly faster parsing than pure Python parsers.
Implements selective parsing and pre-compiled CSS selectors for maximum speed.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

try:
    from lxml import html, etree
    LXML_AVAILABLE = True
except ImportError:
    LXML_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("lxml not available, falling back to selectolax")

from src.ingest.category_scanner import DiscoveredProduct

logger = logging.getLogger(__name__)


class FastParser:
    """
    High-performance HTML parser using lxml.
    
    Features:
    - C-based parsing (much faster than pure Python)
    - Selective parsing (only extract needed elements)
    - Pre-compiled XPath expressions
    - Parallel parsing support
    """
    
    def __init__(self):
        """Initialize fast parser."""
        if not LXML_AVAILABLE:
            logger.warning("lxml not available, FastParser will use fallback")
        self._xpath_cache: Dict[str, etree.XPath] = {}
    
    def _get_xpath(self, xpath_expr: str) -> etree.XPath:
        """Get or compile XPath expression (cached)."""
        if xpath_expr not in self._xpath_cache:
            self._xpath_cache[xpath_expr] = etree.XPath(xpath_expr)
        return self._xpath_cache[xpath_expr]
    
    def parse_price(self, text: str) -> Optional[Decimal]:
        """
        Parse price from text string.
        
        Args:
            text: Text containing price
            
        Returns:
            Decimal price or None if parsing fails
        """
        if not text:
            return None
        
        # Remove common non-numeric characters except decimal point
        cleaned = text.replace("$", "").replace(",", "").strip()
        
        # Extract first number sequence
        import re
        match = re.search(r"(\d+\.?\d*)", cleaned)
        if match:
            try:
                return Decimal(match.group(1))
            except (InvalidOperation, ValueError):
                pass
        
        return None
    
    def extract_text(self, element, selector: str = None) -> Optional[str]:
        """
        Extract text from element using CSS selector or XPath.
        
        Args:
            element: lxml element or root
            selector: CSS selector or XPath (optional)
            
        Returns:
            Text content or None
        """
        if selector:
            try:
                # Try CSS selector first (if element supports it)
                if hasattr(element, 'cssselect'):
                    found = element.cssselect(selector)
                    if found:
                        return found[0].text_content().strip()
                # Fall back to XPath
                xpath = self._get_xpath(selector)
                found = xpath(element)
                if found:
                    return found[0].text_content().strip() if hasattr(found[0], 'text_content') else str(found[0]).strip()
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                return None
        
        # Extract all text from element
        if hasattr(element, 'text_content'):
            return element.text_content().strip()
        elif hasattr(element, 'text'):
            return element.text.strip() if element.text else None
        else:
            return str(element).strip()
    
    def extract_products_amazon(
        self,
        html_content: str,
        base_url: str = "",
    ) -> List[DiscoveredProduct]:
        """
        Extract products from Amazon category page using fast parsing.
        
        Args:
            html_content: HTML content
            base_url: Base URL for resolving relative links
            
        Returns:
            List of DiscoveredProduct objects
        """
        if not LXML_AVAILABLE:
            # Fallback to selectolax
            from selectolax.parser import HTMLParser
            parser = HTMLParser(html_content)
            products = []
            for item in parser.css('[data-asin]'):
                asin = item.attributes.get('data-asin')
                if not asin or asin == "0":
                    continue
                
                # Extract title
                title_elem = item.css_first('.s-title-instructions-style')
                title = title_elem.text(strip=True) if title_elem else None
                
                # Extract price
                price_elem = item.css_first('.a-price .a-offscreen')
                price = self.parse_price(price_elem.text(strip=True)) if price_elem else None
                
                # Extract original price
                orig_price_elem = item.css_first('.a-price.a-text-price .a-offscreen')
                orig_price = self.parse_price(orig_price_elem.text(strip=True)) if orig_price_elem else None
                
                # Extract URL
                link_elem = item.css_first('h2 a')
                url = urljoin(base_url, link_elem.attributes.get('href', '')) if link_elem else None
                
                if title and url:
                    products.append(DiscoveredProduct(
                        sku=asin,
                        title=title,
                        url=url,
                        current_price=price,
                        original_price=orig_price,
                        store="amazon_us",
                    ))
            
            return products
        
        # Use lxml for faster parsing
        try:
            tree = html.fromstring(html_content)
            products = []
            
            # Find all product items with data-asin
            items = tree.xpath('//div[@data-asin and @data-asin != "0"]')
            
            for item in items:
                asin = item.get('data-asin')
                if not asin:
                    continue
                
                # Extract title (faster with XPath)
                title_elem = item.xpath('.//h2[@class="s-title-instructions-style"]//text()')
                title = " ".join(title_elem).strip() if title_elem else None
                
                # Extract price
                price_elem = item.xpath('.//span[@class="a-offscreen"]/text()')
                price = None
                orig_price = None
                
                if price_elem:
                    # First price is usually current price
                    price = self.parse_price(price_elem[0] if price_elem else None)
                    # Look for strikethrough price
                    strikethrough = item.xpath('.//span[@class="a-price a-text-price"]//span[@class="a-offscreen"]/text()')
                    if strikethrough:
                        orig_price = self.parse_price(strikethrough[0])
                
                # Extract URL
                link = item.xpath('.//h2//a/@href')
                url = urljoin(base_url, link[0]) if link else None
                
                # Extract image
                img = item.xpath('.//img[@data-image-latency]/@src')
                image_url = img[0] if img else None
                
                if title and url:
                    products.append(DiscoveredProduct(
                        sku=asin,
                        title=title,
                        url=url,
                        current_price=price,
                        original_price=orig_price,
                        store="amazon_us",
                        image_url=image_url,
                    ))
            
            return products
        
        except Exception as e:
            logger.error(f"Error parsing Amazon page with lxml: {e}")
            return []
    
    def extract_products_generic(
        self,
        html_content: str,
        product_selector: str,
        title_selector: str,
        price_selector: str,
        url_selector: str = "a",
        sku_selector: Optional[str] = None,
        base_url: str = "",
    ) -> List[DiscoveredProduct]:
        """
        Generic product extraction using CSS selectors.
        
        Args:
            html_content: HTML content
            product_selector: CSS selector for product container
            title_selector: CSS selector for product title
            price_selector: CSS selector for price
            url_selector: CSS selector for product URL
            sku_selector: Optional CSS selector for SKU
            base_url: Base URL for resolving relative links
            
        Returns:
            List of DiscoveredProduct objects
        """
        if not LXML_AVAILABLE:
            # Fallback
            from selectolax.parser import HTMLParser
            parser = HTMLParser(html_content)
            products = []
            for item in parser.css(product_selector):
                title_elem = item.css_first(title_selector)
                price_elem = item.css_first(price_selector)
                url_elem = item.css_first(url_selector)
                sku_elem = item.css_first(sku_selector) if sku_selector else None
                
                title = title_elem.text(strip=True) if title_elem else None
                price = self.parse_price(price_elem.text(strip=True)) if price_elem else None
                url = urljoin(base_url, url_elem.attributes.get('href', '')) if url_elem else None
                sku = sku_elem.text(strip=True) if sku_elem else (url.split('/')[-1] if url else None)
                
                if title and url:
                    products.append(DiscoveredProduct(
                        sku=sku or "unknown",
                        title=title,
                        url=url,
                        current_price=price,
                        store="",
                    ))
            
            return products
        
        # Use lxml
        try:
            tree = html.fromstring(html_content)
            products = []
            
            # Convert CSS selector to XPath (simplified)
            items = tree.xpath(f'//*[contains(@class, "{product_selector.split(".")[-1]}")]') if '.' in product_selector else tree.cssselect(product_selector)
            
            for item in items:
                # Extract title
                title_elem = item.cssselect(title_selector) if hasattr(item, 'cssselect') else item.xpath(f'.//*[contains(@class, "{title_selector}")]')
                title = title_elem[0].text_content().strip() if title_elem else None
                
                # Extract price
                price_elem = item.cssselect(price_selector) if hasattr(item, 'cssselect') else item.xpath(f'.//*[contains(@class, "{price_selector}")]')
                price = self.parse_price(price_elem[0].text_content()) if price_elem else None
                
                # Extract URL
                url_elem = item.cssselect(url_selector) if hasattr(item, 'cssselect') else item.xpath(f'.//{url_selector}')
                url = urljoin(base_url, url_elem[0].get('href', '')) if url_elem and hasattr(url_elem[0], 'get') else None
                
                # Extract SKU
                sku = None
                if sku_selector:
                    sku_elem = item.cssselect(sku_selector) if hasattr(item, 'cssselect') else item.xpath(f'.//*[contains(@class, "{sku_selector}")]')
                    sku = sku_elem[0].text_content().strip() if sku_elem else None
                
                if not sku and url:
                    sku = url.split('/')[-1].split('?')[0]
                
                if title and url:
                    products.append(DiscoveredProduct(
                        sku=sku or "unknown",
                        title=title,
                        url=url,
                        current_price=price,
                        store="",
                    ))
            
            return products
        
        except Exception as e:
            logger.error(f"Error parsing with lxml: {e}")
            return []
    
    def parse_parallel(
        self,
        html_contents: List[str],
        parser_func: callable,
    ) -> List[List[DiscoveredProduct]]:
        """
        Parse multiple HTML contents in parallel.
        
        Args:
            html_contents: List of HTML strings
            parser_func: Function to parse each HTML
            
        Returns:
            List of product lists
        """
        import concurrent.futures
        
        # Use ThreadPoolExecutor for CPU-bound parsing
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(parser_func, html) for html in html_contents]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        return results


# Global fast parser instance
fast_parser = FastParser()
