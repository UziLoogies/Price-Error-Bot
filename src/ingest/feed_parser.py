"""Product feed parser for RSS/JSON feeds.

Parses RSS, Atom, and JSON product feeds to discover products
from structured data sources.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET

import httpx

from src.ingest.category_scanner import DiscoveredProduct
from src.ingest.proxy_manager import proxy_rotator
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class FeedParser:
    """
    Parses product feeds in various formats.
    
    Features:
    - Parse RSS/Atom product feeds
    - Extract product data from JSON/XML feeds
    - Support common feed formats (Google Shopping, product feeds)
    - Discover products from feeds
    """
    
    def __init__(self):
        """Initialize feed parser."""
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def parse_rss_feed(
        self,
        feed_url: str,
        store: str = "",
    ) -> List[DiscoveredProduct]:
        """
        Parse RSS/Atom feed and extract product data.
        
        Args:
            feed_url: Feed URL
            store: Store identifier
            
        Returns:
            List of DiscoveredProduct objects
        """
        client = await self._get_client()
        domain = urlparse(feed_url).netloc
        
        # Rate limit
        await rate_limiter.acquire_adaptive(domain)
        
        try:
            response = await client.get(feed_url, timeout=30.0)
            response.raise_for_status()
            
            # Parse XML
            root = ET.fromstring(response.content)
            
            products = []
            
            # Handle RSS format
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            
            for item in items:
                try:
                    # Extract title
                    title_elem = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                    title = title_elem.text if title_elem is not None else None
                    
                    # Extract link
                    link_elem = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
                    url = None
                    if link_elem is not None:
                        url = link_elem.text or link_elem.get("href")
                    
                    # Extract price (common in product feeds)
                    price_elem = item.find(".//{http://base.google.com/ns/1.0}price")
                    if price_elem is None:
                        price_elem = item.find("price")
                    
                    current_price = None
                    if price_elem is not None and price_elem.text:
                        try:
                            # Remove currency symbols
                            price_text = price_elem.text.replace("$", "").replace(",", "").strip()
                            current_price = Decimal(price_text)
                        except Exception:
                            pass
                    
                    # Extract SKU
                    sku_elem = item.find(".//{http://base.google.com/ns/1.0}id") or item.find("id")
                    sku = sku_elem.text if sku_elem is not None else None
                    if not sku and url:
                        # Extract SKU from URL
                        sku = url.split("/")[-1].split("?")[0]
                    
                    # Extract image
                    image_elem = item.find(".//{http://base.google.com/ns/1.0}image_link") or item.find("image")
                    image_url = image_elem.text if image_elem is not None else None
                    
                    if title and url and current_price:
                        products.append(DiscoveredProduct(
                            sku=sku or "unknown",
                            title=title,
                            url=url,
                            current_price=current_price,
                            store=store,
                            image_url=image_url,
                        ))
                
                except Exception as e:
                    logger.debug(f"Error parsing feed item: {e}")
                    continue
            
            logger.info(f"Parsed {len(products)} products from RSS feed {feed_url}")
            return products
        
        except Exception as e:
            logger.error(f"Error parsing RSS feed {feed_url}: {e}")
            return []
    
    async def parse_json_feed(
        self,
        feed_url: str,
        store: str = "",
    ) -> List[DiscoveredProduct]:
        """
        Parse JSON product feed.
        
        Args:
            feed_url: Feed URL
            store: Store identifier
            
        Returns:
            List of DiscoveredProduct objects
        """
        client = await self._get_client()
        domain = urlparse(feed_url).netloc
        
        # Rate limit
        await rate_limiter.acquire_adaptive(domain)
        
        try:
            response = await client.get(feed_url, timeout=30.0)
            response.raise_for_status()
            
            data = response.json()
            
            products = []
            
            # Handle different JSON feed formats
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # Common keys for product arrays
                for key in ["products", "items", "data", "results"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
            
            for item in items:
                try:
                    # Extract common fields
                    title = item.get("title") or item.get("name")
                    url = item.get("url") or item.get("link")
                    price = item.get("price") or item.get("current_price")
                    sku = item.get("sku") or item.get("id") or item.get("product_id")
                    image_url = item.get("image_url") or item.get("image") or item.get("thumbnail")
                    
                    # Parse price
                    current_price = None
                    if price:
                        try:
                            if isinstance(price, str):
                                price = price.replace("$", "").replace(",", "").strip()
                            current_price = Decimal(str(price))
                        except Exception:
                            pass
                    
                    if title and url and current_price:
                        products.append(DiscoveredProduct(
                            sku=str(sku) if sku else "unknown",
                            title=title,
                            url=url,
                            current_price=current_price,
                            store=store,
                            image_url=image_url,
                        ))
                
                except Exception as e:
                    logger.debug(f"Error parsing JSON feed item: {e}")
                    continue
            
            logger.info(f"Parsed {len(products)} products from JSON feed {feed_url}")
            return products
        
        except Exception as e:
            logger.error(f"Error parsing JSON feed {feed_url}: {e}")
            return []
    
    async def discover_feeds(self, store: str, base_url: str) -> List[str]:
        """
        Discover product feed URLs for a store.
        
        Common locations:
        - /products.json
        - /feeds/products.xml
        - /rss/products
        - /api/products
        
        Args:
            store: Store identifier
            base_url: Base URL of the store
            
        Returns:
            List of feed URLs
        """
        feeds = []
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Common feed paths
        common_paths = [
            "/products.json",
            "/feeds/products.xml",
            "/rss/products",
            "/api/products",
            "/feed/products",
            "/products/feed",
        ]
        
        client = await self._get_client()
        
        for path in common_paths:
            feed_url = urljoin(base, path)
            try:
                response = await client.head(feed_url, timeout=5.0)
                if response.status_code == 200:
                    feeds.append(feed_url)
            except Exception:
                pass
        
        logger.info(f"Discovered {len(feeds)} feeds for {store}")
        return feeds


# Global feed parser instance
feed_parser = FeedParser()
