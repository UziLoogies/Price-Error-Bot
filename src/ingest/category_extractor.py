"""Category extraction utility for discovering categories from product URLs."""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from selectolax.parser import HTMLParser

from src.ingest.proxy_manager import proxy_rotator
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Store domain mapping
STORE_DOMAINS = {
    "www.bestbuy.com": "bestbuy",
    "bestbuy.com": "bestbuy",
    "www.amazon.com": "amazon_us",
    "amazon.com": "amazon_us",
    "www.walmart.com": "walmart",
    "walmart.com": "walmart",
    "www.target.com": "target",
    "target.com": "target",
    "www.newegg.com": "newegg",
    "newegg.com": "newegg",
    "www.microcenter.com": "microcenter",
    "microcenter.com": "microcenter",
    "www.gamestop.com": "gamestop",
    "gamestop.com": "gamestop",
    "www.bhphotovideo.com": "bhphotovideo",
    "bhphotovideo.com": "bhphotovideo",
    "www.kohls.com": "kohls",
    "kohls.com": "kohls",
    "www.officedepot.com": "officedepot",
    "officedepot.com": "officedepot",
    "www.ebay.com": "ebay",
    "ebay.com": "ebay",
    "www.macys.com": "macys",
    "macys.com": "macys",
    "www.costco.com": "costco",
    "costco.com": "costco",
    "www.homedepot.com": "homedepot",
    "homedepot.com": "homedepot",
    "www.lowes.com": "lowes",
    "lowes.com": "lowes",
}


@dataclass
class CategoryInfo:
    """Discovered category information."""
    category_url: str
    category_name: str
    store: str
    confidence: float = 0.8


def detect_store_from_url(url: str) -> Optional[str]:
    """
    Detect store name from product URL.
    
    Args:
        url: Product URL
        
    Returns:
        Store identifier or None if not recognized
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Try exact match first
        if domain in STORE_DOMAINS:
            return STORE_DOMAINS[domain]
        
        # Try without www prefix
        domain_no_www = domain.replace("www.", "")
        if domain_no_www in STORE_DOMAINS:
            return STORE_DOMAINS[domain_no_www]
        
        # Try with www prefix
        domain_with_www = f"www.{domain}" if not domain.startswith("www.") else domain
        if domain_with_www in STORE_DOMAINS:
            return STORE_DOMAINS[domain_with_www]
        
        return None
    except Exception as e:
        logger.debug(f"Error detecting store from URL: {e}")
        return None


async def extract_bestbuy_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Best Buy product page."""
    parser = HTMLParser(html)
    base_url = "https://www.bestbuy.com"
    
    # Method 1: Breadcrumb navigation (most reliable)
    breadcrumbs = parser.css('nav[aria-label="Breadcrumb"] a, .breadcrumb a, [data-testid="breadcrumb"] a')
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        # Look for category links (contain /site/ or /c/ but not /product/)
        if ('/site/' in href or '/c/' in href) and '/product/' not in href:
            category_url = urljoin(base_url, href)
            # Clean up URL (remove query params that might be product-specific)
            category_url = category_url.split('?')[0]
            
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered Category",
                store="bestbuy",
                confidence=0.9
            )
    
    # Method 2: "Shop all" or "See more" links
    shop_links = parser.css('a[href*="/site/"]:not([href*="/product/"]), a[href*="/c/"]:not([href*="/product/"])')
    for link in shop_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True).lower()
        
        # Look for shop-related text
        if any(keyword in text for keyword in ['shop', 'view all', 'see all', 'browse']):
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered from Product",
                store="bestbuy",
                confidence=0.7
            )
    
    # Method 3: Find any /site/ link that's not a product
    site_links = parser.css('a[href*="/site/"]')
    for link in site_links:
        href = link.attributes.get('href', '')
        if '/product/' not in href:
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name="Discovered from Product",
                store="bestbuy",
                confidence=0.6
            )
    
    return None


async def extract_amazon_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Amazon product page."""
    parser = HTMLParser(html)
    base_url = "https://www.amazon.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('#wayfinding-breadcrumbs_feature_div a, .a-breadcrumb a, [data-testid="breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'all']:
            category_name_parts.append(text)
        
        # Look for category/search links
        if '/s?k=' in href or '/s?rh=' in href or '/gp/browse.html' in href:
            category_url = urljoin(base_url, href)
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="amazon_us",
                confidence=0.9
            )
    
    # Method 2: Department navigation
    dept_links = parser.css('a[href*="/s?k="], a[href*="/s?rh="], a[href*="/gp/browse.html"]')
    for link in dept_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True)
        
        if text and len(text) > 3:  # Filter out very short links
            category_url = urljoin(base_url, href)
            return CategoryInfo(
                category_url=category_url,
                category_name=text,
                store="amazon_us",
                confidence=0.7
            )
    
    return None


async def extract_walmart_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Walmart product page."""
    parser = HTMLParser(html)
    base_url = "https://www.walmart.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, [data-testid="breadcrumb"] a, nav[aria-label*="Breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'walmart']:
            category_name_parts.append(text)
        
        # Look for category/browse links
        if '/browse/' in href or '/ip/' not in href:
            category_url = urljoin(base_url, href)
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="walmart",
                confidence=0.9
            )
    
    # Method 2: "Shop all" or department links
    shop_links = parser.css('a[href*="/browse/"]:not([href*="/ip/"]), a[href*="/cp/"]')
    for link in shop_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True).lower()
        
        if any(keyword in text for keyword in ['shop', 'view all', 'see all', 'browse', 'department']):
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered from Product",
                store="walmart",
                confidence=0.7
            )
    
    return None


async def extract_target_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Target product page."""
    parser = HTMLParser(html)
    base_url = "https://www.target.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('[data-test="breadcrumb"] a, .breadcrumb a, nav[aria-label*="Breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'target']:
            category_name_parts.append(text)
        
        # Look for category links (contain /c/ but not /p/)
        if '/c/' in href and '/p/' not in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="target",
                confidence=0.9
            )
    
    # Method 2: "Shop all" or category links
    shop_links = parser.css('a[href*="/c/"]:not([href*="/p/"])')
    for link in shop_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True).lower()
        
        if any(keyword in text for keyword in ['shop', 'view all', 'see all', 'browse']):
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered from Product",
                store="target",
                confidence=0.7
            )
    
    return None


async def extract_newegg_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Newegg product page."""
    parser = HTMLParser(html)
    base_url = "https://www.newegg.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, nav[aria-label*="Breadcrumb"] a, [data-testid="breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'newegg']:
            category_name_parts.append(text)
        
        # Look for category links (contain /c/ or /p/ but not product-specific)
        if ('/c/' in href or '/p/' in href) and '/product/' not in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="newegg",
                confidence=0.9
            )
    
    # Method 2: Category links
    cat_links = parser.css('a[href*="/c/"]:not([href*="/product/"]), a[href*="/p/"]:not([href*="/product/"])')
    for link in cat_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True).lower()
        
        if any(keyword in text for keyword in ['shop', 'view all', 'see all', 'browse', 'category']):
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered from Product",
                store="newegg",
                confidence=0.7
            )
    
    return None


async def extract_microcenter_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Micro Center product page."""
    parser = HTMLParser(html)
    base_url = "https://www.microcenter.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, nav[aria-label*="Breadcrumb"] a, [data-testid="breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'micro center']:
            category_name_parts.append(text)
        
        # Look for category links
        if '/category/' in href or '/shop/' in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="microcenter",
                confidence=0.9
            )
    
    # Method 2: Shop/category links
    shop_links = parser.css('a[href*="/category/"], a[href*="/shop/"]')
    for link in shop_links:
        href = link.attributes.get('href', '')
        text = link.text(strip=True).lower()
        
        if any(keyword in text for keyword in ['shop', 'view all', 'see all', 'browse']):
            category_url = urljoin(base_url, href).split('?')[0]
            return CategoryInfo(
                category_url=category_url,
                category_name=text or "Discovered from Product",
                store="microcenter",
                confidence=0.7
            )
    
    return None


async def extract_costco_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Costco product page."""
    parser = HTMLParser(html)
    base_url = "https://www.costco.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, nav[aria-label*="Breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'costco']:
            category_name_parts.append(text)
        
        # Look for category links (contain .product. but category pages)
        if '/.product.' in href or '/Browse/' in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="costco",
                confidence=0.8
            )
    
    return None


async def extract_homedepot_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Home Depot product page."""
    parser = HTMLParser(html)
    base_url = "https://www.homedepot.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, nav[aria-label*="Breadcrumb"] a, [data-testid="breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', 'home depot']:
            category_name_parts.append(text)
        
        # Look for category links (contain /b/ or /c/ but not product-specific)
        if ('/b/' in href or '/c/' in href) and '/p/' not in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="homedepot",
                confidence=0.9
            )
    
    return None


async def extract_lowes_category(product_url: str, html: str) -> Optional[CategoryInfo]:
    """Extract category from Lowe's product page."""
    parser = HTMLParser(html)
    base_url = "https://www.lowes.com"
    
    # Method 1: Breadcrumb navigation
    breadcrumbs = parser.css('.breadcrumb a, nav[aria-label*="Breadcrumb"] a, [data-testid="breadcrumb"] a')
    category_name_parts = []
    
    for crumb in breadcrumbs:
        href = crumb.attributes.get('href', '')
        text = crumb.text(strip=True)
        
        if text and text.lower() not in ['home', "lowe's"]:
            category_name_parts.append(text)
        
        # Look for category links (contain /c/ or /pl/ but not product-specific)
        if ('/c/' in href or '/pl/' in href) and '/pd/' not in href:
            category_url = urljoin(base_url, href).split('?')[0]
            category_name = ' > '.join(category_name_parts) if category_name_parts else "Discovered Category"
            
            return CategoryInfo(
                category_url=category_url,
                category_name=category_name,
                store="lowes",
                confidence=0.9
            )
    
    return None


async def extract_category_from_product(product_url: str) -> Optional[CategoryInfo]:
    """
    Extract category information from a product page.
    
    Args:
        product_url: Full URL to a product page
        
    Returns:
        CategoryInfo with category URL, name, store, and confidence, or None if extraction fails
    """
    # Detect store from URL (may be a short link)
    store = detect_store_from_url(product_url)
    
    # Fetch product page HTML
    try:
        # Get proxy if available
        proxy = None
        if proxy_rotator.has_proxies():
            proxy = await proxy_rotator.get_next_proxy()
        
        # Rate limit
        domain = urlparse(product_url).netloc
        await rate_limiter.acquire_with_interval(domain, 10, 20, 5)
        
        # Fetch page
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            proxy=proxy.url if proxy else None
        ) as client:
            response = await client.get(product_url)
            response.raise_for_status()
            html = response.text
            final_url = str(response.url)
            if not store:
                store = detect_store_from_url(final_url)
                if store:
                    logger.info(f"Resolved short link to {final_url} (store={store})")
        
        # Report proxy success
        if proxy:
            await proxy_rotator.report_success(proxy.id)
    
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching product page: {e}")
        if proxy:
            await proxy_rotator.report_failure(proxy.id)
        return None
    except Exception as e:
        logger.error(f"Error fetching product page: {e}")
        if proxy:
            await proxy_rotator.report_failure(proxy.id)
        return None
    
    # Store-specific extraction
    if not store:
        logger.warning(f"Could not determine store for URL: {product_url}")
        return None
    if store == "bestbuy":
        return await extract_bestbuy_category(product_url, html)
    elif store == "amazon_us":
        return await extract_amazon_category(product_url, html)
    elif store == "walmart":
        return await extract_walmart_category(product_url, html)
    elif store == "target":
        return await extract_target_category(product_url, html)
    elif store == "newegg":
        return await extract_newegg_category(product_url, html)
    elif store == "microcenter":
        return await extract_microcenter_category(product_url, html)
    elif store == "costco":
        return await extract_costco_category(product_url, html)
    elif store == "homedepot":
        return await extract_homedepot_category(product_url, html)
    elif store == "lowes":
        return await extract_lowes_category(product_url, html)
    
    logger.warning(f"Category extraction not yet implemented for store: {store}")
    return None
