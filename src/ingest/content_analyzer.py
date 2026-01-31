"""Content analyzer for bot detection and content fingerprinting.

Analyzes HTML responses to detect:
- Bot challenges (CAPTCHA, Cloudflare, rate limiting)
- Valid product content vs error pages
- Content quality for parsing confidence
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional, Dict, List

from selectolax.parser import HTMLParser

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ContentAnalysis:
    """Result of content analysis."""
    
    is_valid: bool                      # Content appears to be valid product page
    is_blocked: bool                    # Detected bot challenge or block
    block_type: Optional[str]           # Type of block: captcha, cloudflare, 403, rate_limit
    product_count_estimate: int         # Estimated number of products found
    confidence: float                   # Confidence in analysis (0.0 - 1.0)
    content_hash: str                   # Hash of meaningful content
    page_title: Optional[str]           # Page title for debugging
    content_length: int                 # Length of HTML content


# Store-specific product indicators (CSS selectors that indicate real product content)
STORE_INDICATORS: Dict[str, List[str]] = {
    "amazon_us": [
        '[data-asin]',
        '.s-result-item',
        '.a-price',
        '[data-component-type="s-search-result"]',
    ],
    "walmart": [
        '[data-item-id]',
        '[data-product-id]',
        '.product-card',
        '.price-main',
    ],
    "target": [
        '[data-test="product-grid"]',
        '.ProductCard',
        '[data-test="product-price"]',
    ],
    "bestbuy": [
        '.sku-item',
        '[data-sku-id]',
        '.priceView-customer-price',
    ],
    "costco": [
        '.product-tile',
        '.product',
        '[data-product-id]',
    ],
    "newegg": [
        '.item-cell',
        '.item-container',
        '[data-dealpromoid]',
    ],
    "homedepot": [
        '.browse-search__pod',
        '[data-component="ProductPod"]',
    ],
    "lowes": [
        '[data-selector="splp-prd-image-container"]',
        '.product-card',
    ],
    "macys": [
        '.productThumbnail',
        '.product-thumbnail',
    ],
    "ebay": [
        '[data-testid="item-card"]',
        '.deal-item',
        '.s-item',
    ],
    # Deal aggregators
    "saveyourdeals": [
        '[class*="deal"]',
        '[class*="product"]',
        'a[href*="amazon.com"]',
    ],
    "slickdeals": [
        '[class*="dealCard"]',
        '[data-deal-id]',
        '.fpDeal',
    ],
    "woot": [
        '[class*="deal"]',
        '[class*="event"]',
        '[data-eventid]',
    ],
}

# Block indicators - patterns that suggest the page is blocked or a bot challenge
BLOCK_PATTERNS = [
    # CAPTCHA indicators
    (r'enter the characters', 'captcha'),
    (r'prove you\'?re not a robot', 'captcha'),
    (r'captcha', 'captcha'),
    (r'verify you are a human', 'captcha'),
    (r'robot check', 'captcha'),
    (r'unusual traffic', 'captcha'),
    
    # Cloudflare
    (r'cloudflare', 'cloudflare'),
    (r'checking your browser', 'cloudflare'),
    (r'ray id', 'cloudflare'),
    (r'please wait while we verify', 'cloudflare'),
    
    # Rate limiting / blocking
    (r'access denied', 'access_denied'),
    (r'forbidden', 'access_denied'),
    (r'request has been blocked', 'rate_limit'),
    (r'too many requests', 'rate_limit'),
    (r'rate limit', 'rate_limit'),
    
    # Bot detection
    (r'automation tools', 'bot_detected'),
    (r'pardon our interruption', 'bot_detected'),
    (r'enable javascript', 'js_required'),
    (r'enable cookies', 'cookies_required'),
    
    # Anti-bot services
    (r'akamai', 'akamai'),
    (r'incapsula', 'incapsula'),
    (r'distil', 'distil'),
    (r'perimeterx', 'perimeter_x'),
]


class ContentAnalyzer:
    """Analyzes HTML content for validity and bot detection."""
    
    def __init__(self):
        # Compile block patterns for efficiency
        self._block_patterns = [
            (re.compile(pattern, re.IGNORECASE), block_type)
            for pattern, block_type in BLOCK_PATTERNS
        ]
    
    def analyze(self, html: str, store: str) -> ContentAnalysis:
        """
        Analyze HTML content for validity and bot detection.
        
        Args:
            html: Raw HTML content
            store: Store identifier
            
        Returns:
            ContentAnalysis with detailed results
        """
        if not html:
            return ContentAnalysis(
                is_valid=False,
                is_blocked=False,
                block_type=None,
                product_count_estimate=0,
                confidence=0.0,
                content_hash="",
                page_title=None,
                content_length=0,
            )
        
        content_length = len(html)
        
        # Parse HTML
        try:
            parser = HTMLParser(html)
        except Exception as e:
            logger.debug(f"Failed to parse HTML: {e}")
            return ContentAnalysis(
                is_valid=False,
                is_blocked=False,
                block_type=None,
                product_count_estimate=0,
                confidence=0.0,
                content_hash=self._compute_hash(html),
                page_title=None,
                content_length=content_length,
            )
        
        # Get page title
        title_elem = parser.css_first('title')
        page_title = title_elem.text(strip=True) if title_elem else None
        
        # Check for blocks first
        block_type = self._detect_block(html, page_title)
        if block_type:
            return ContentAnalysis(
                is_valid=False,
                is_blocked=True,
                block_type=block_type,
                product_count_estimate=0,
                confidence=0.9,  # High confidence in block detection
                content_hash=self._compute_hash(html),
                page_title=page_title,
                content_length=content_length,
            )
        
        # Count product indicators
        product_count = self._count_products(parser, store)
        
        # Determine validity
        min_expected = settings.min_expected_products
        is_valid = product_count >= min_expected
        
        # Calculate confidence based on product count
        if product_count >= 10:
            confidence = 0.95
        elif product_count >= 5:
            confidence = 0.85
        elif product_count >= 1:
            confidence = 0.7
        else:
            confidence = 0.3
        
        return ContentAnalysis(
            is_valid=is_valid,
            is_blocked=False,
            block_type=None,
            product_count_estimate=product_count,
            confidence=confidence,
            content_hash=self._compute_hash(html),
            page_title=page_title,
            content_length=content_length,
        )
    
    def _detect_block(self, html: str, page_title: Optional[str]) -> Optional[str]:
        """
        Detect if the page is a bot challenge or block.
        
        Args:
            html: Raw HTML content
            page_title: Page title
            
        Returns:
            Block type string or None
        """
        # Normalize content for pattern matching
        content = html.lower()
        if page_title:
            content = f"{page_title.lower()} {content}"
        
        # Check each block pattern
        for pattern, block_type in self._block_patterns:
            if pattern.search(content):
                logger.debug(f"Detected block type: {block_type}")
                return block_type
        
        # Check for suspiciously short content (likely error page)
        if len(html) < 1000:
            # Very short pages are often error pages
            if 'error' in content or '404' in content or '403' in content:
                return 'error_page'
        
        return None
    
    def _count_products(self, parser: HTMLParser, store: str) -> int:
        """
        Count product indicators in the parsed HTML.
        
        Args:
            parser: HTMLParser instance
            store: Store identifier
            
        Returns:
            Estimated product count
        """
        indicators = STORE_INDICATORS.get(store, [])
        
        if not indicators:
            # Fallback: try generic product indicators
            indicators = [
                '[class*="product"]',
                '[class*="item"]',
                '[data-sku]',
                '[data-product]',
            ]
        
        max_count = 0
        for selector in indicators:
            try:
                elements = parser.css(selector)
                count = len(elements)
                if count > max_count:
                    max_count = count
            except Exception:
                continue
        
        return max_count
    
    def _compute_hash(self, html: str) -> str:
        """
        Compute a hash of meaningful content.
        
        Excludes dynamic elements like timestamps, session IDs, etc.
        
        Args:
            html: Raw HTML content
            
        Returns:
            MD5 hash of normalized content
        """
        # Remove common dynamic elements
        normalized = html
        
        # Remove script content
        normalized = re.sub(r'<script[^>]*>.*?</script>', '', normalized, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove inline styles
        normalized = re.sub(r'<style[^>]*>.*?</style>', '', normalized, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove comments
        normalized = re.sub(r'<!--.*?-->', '', normalized, flags=re.DOTALL)
        
        # Remove whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Hash the normalized content
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def get_block_type_label(self, block_type: Optional[str]) -> str:
        """
        Get a human-readable label for a block type.
        
        Args:
            block_type: Block type identifier
            
        Returns:
            Human-readable label
        """
        labels = {
            'captcha': 'CAPTCHA Challenge',
            'cloudflare': 'Cloudflare Protection',
            'access_denied': 'Access Denied (403)',
            'rate_limit': 'Rate Limited (429)',
            'bot_detected': 'Bot Detection',
            'js_required': 'JavaScript Required',
            'cookies_required': 'Cookies Required',
            'akamai': 'Akamai Protection',
            'incapsula': 'Incapsula Protection',
            'distil': 'Distil Protection',
            'perimeter_x': 'PerimeterX Protection',
            'error_page': 'Error Page',
        }
        return labels.get(block_type, block_type or 'Unknown')


# Global instance
content_analyzer = ContentAnalyzer()
