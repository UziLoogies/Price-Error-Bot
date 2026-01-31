"""Sitemap scanner for comprehensive product discovery.

Parses XML sitemaps to discover all product URLs, including hidden
or orphaned listings that might not appear on category pages.
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Set, Optional, Dict
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET

import httpx

from src.config import settings
from src.ingest.proxy_manager import proxy_rotator
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class SitemapScanner:
    """
    Scans XML sitemaps to discover product URLs.
    
    Features:
    - Parse XML sitemaps (sitemap.xml, sitemap_index.xml)
    - Extract product URLs from sitemaps
    - Discover category sitemaps
    - Maintain catalog of all product URLs
    - Detect newly added products by comparing sitemap snapshots
    """
    
    def __init__(self):
        """Initialize sitemap scanner."""
        self.enabled = getattr(settings, 'sitemap_scan_enabled', True)
        self.product_limit = getattr(settings, 'sitemap_product_limit', 10000)
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
    
    async def discover_sitemaps(self, base_url: str) -> List[str]:
        """
        Discover sitemap URLs for a site.
        
        Common locations:
        - /sitemap.xml
        - /sitemap_index.xml
        - /sitemaps/sitemap.xml
        - robots.txt (Sitemap directive)
        
        Args:
            base_url: Base URL of the site
            
        Returns:
            List of sitemap URLs
        """
        if not self.enabled:
            return []
        
        sitemaps = []
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Common sitemap locations
        common_paths = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemaps/sitemap.xml",
            "/sitemap1.xml",
        ]
        
        client = await self._get_client()
        
        # Check robots.txt for Sitemap directive
        try:
            robots_url = urljoin(base, "/robots.txt")
            response = await client.get(robots_url, timeout=10.0)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        sitemaps.append(sitemap_url)
        except Exception as e:
            logger.debug(f"Error checking robots.txt for {base_url}: {e}")
        
        # Check common paths
        for path in common_paths:
            sitemap_url = urljoin(base, path)
            try:
                response = await client.head(sitemap_url, timeout=5.0)
                if response.status_code == 200:
                    sitemaps.append(sitemap_url)
            except Exception:
                pass
        
        logger.info(f"Discovered {len(sitemaps)} sitemaps for {base_url}")
        return sitemaps
    
    async def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """
        Parse a sitemap XML and extract URLs.
        
        Args:
            sitemap_url: URL of the sitemap
            
        Returns:
            List of URLs from the sitemap
        """
        if not self.enabled:
            return []
        
        client = await self._get_client()
        domain = urlparse(sitemap_url).netloc
        
        # Rate limit
        await rate_limiter.acquire_adaptive(domain)
        
        try:
            response = await client.get(sitemap_url, timeout=30.0)
            response.raise_for_status()
            
            # Parse XML
            root = ET.fromstring(response.content)
            
            # Handle sitemap index (contains other sitemaps)
            if root.tag.endswith("sitemapindex"):
                sitemap_urls = []
                for sitemap_elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
                    loc_elem = sitemap_elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                    if loc_elem is not None:
                        sitemap_urls.append(loc_elem.text)
                
                # Recursively parse nested sitemaps
                all_urls = []
                for nested_sitemap in sitemap_urls[:10]:  # Limit nested sitemaps
                    nested_urls = await self.parse_sitemap(nested_sitemap)
                    all_urls.extend(nested_urls)
                return all_urls
            
            # Handle regular sitemap (contains URLs)
            urls = []
            for url_elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
                loc_elem = url_elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if loc_elem is not None:
                    urls.append(loc_elem.text)
            
            logger.debug(f"Parsed {len(urls)} URLs from {sitemap_url}")
            return urls
        
        except Exception as e:
            logger.error(f"Error parsing sitemap {sitemap_url}: {e}")
            return []
    
    async def extract_product_urls(
        self,
        sitemap_url: str,
        product_patterns: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Extract product URLs from a sitemap.
        
        Args:
            sitemap_url: Sitemap URL
            product_patterns: Optional patterns to identify product URLs
            
        Returns:
            List of product URLs
        """
        all_urls = await self.parse_sitemap(sitemap_url)
        
        if not product_patterns:
            # Default patterns for common e-commerce sites
            product_patterns = [
                "/dp/",  # Amazon
                "/product/",
                "/p/",
                "/item/",
                "/products/",
                "?sku=",
                "?product_id=",
            ]
        
        product_urls = []
        for url in all_urls:
            if any(pattern in url.lower() for pattern in product_patterns):
                product_urls.append(url)
        
        # Limit to avoid overload
        if len(product_urls) > self.product_limit:
            logger.warning(
                f"Limiting product URLs from {len(product_urls)} to {self.product_limit}"
            )
            product_urls = product_urls[:self.product_limit]
        
        return product_urls
    
    async def detect_new_products(
        self,
        store: str,
        base_url: str,
    ) -> List[str]:
        """
        Detect newly added products by comparing sitemap snapshots.
        
        Args:
            store: Store identifier
            base_url: Base URL of the store
            
        Returns:
            List of new product URLs
        """
        if not self.enabled:
            return []
        
        # Discover sitemaps
        sitemaps = await self.discover_sitemaps(base_url)
        if not sitemaps:
            return []
        
        # Extract all product URLs
        all_product_urls = set()
        for sitemap_url in sitemaps:
            product_urls = await self.extract_product_urls(sitemap_url)
            all_product_urls.update(product_urls)
        
        # Compare with previous snapshot (would need to store in DB)
        # For now, return all URLs (caller can filter)
        logger.info(f"Found {len(all_product_urls)} product URLs from sitemaps for {store}")
        
        return list(all_product_urls)


# Global sitemap scanner instance
sitemap_scanner = SitemapScanner()
