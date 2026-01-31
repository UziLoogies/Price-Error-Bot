"""Realistic HTTP header generation system.

Builds realistic headers per browser type with proper consistency
and referer chain simulation.
"""

import logging
import random
from typing import Optional, Dict
from urllib.parse import urlparse

from src.ingest.user_agent_pool import user_agent_pool

logger = logging.getLogger(__name__)


class HeaderBuilder:
    """
    Builds realistic HTTP headers for different browser types.
    
    Features:
    - Browser-specific header sets
    - Accept-Language variation
    - Accept-Encoding consistency
    - Referer chain simulation
    - Cookie handling simulation
    """
    
    def __init__(self):
        """Initialize header builder."""
        # Language codes by region
        self.languages = {
            "US": ["en-US,en;q=0.9"],
            "EU": ["en-GB,en;q=0.9", "de-DE,de;q=0.9", "fr-FR,fr;q=0.9"],
            "ASIA": ["en-US,en;q=0.9", "ja-JP,ja;q=0.9", "zh-CN,zh;q=0.9"],
        }
        
        # Common referer patterns
        self.referer_patterns = {
            "amazon.com": ["https://www.google.com/", "https://www.bing.com/", "https://www.amazon.com/"],
            "walmart.com": ["https://www.google.com/", "https://www.walmart.com/"],
            "target.com": ["https://www.google.com/", "https://www.target.com/"],
        }
    
    def build_headers(
        self,
        browser_type: str = "chrome",
        url: str = "",
        referer: Optional[str] = None,
        region: str = "US",
    ) -> Dict[str, str]:
        """
        Build realistic headers for a browser type.
        
        Args:
            browser_type: Browser type ('chrome', 'firefox', 'safari', 'edge')
            url: Target URL
            referer: Referer URL (auto-generated if None)
            region: Geo region for language selection
            
        Returns:
            Dict of HTTP headers
        """
        # Get user agent
        user_agent = user_agent_pool.get_for_browser(browser_type)
        
        # Build base headers
        headers = {
            "User-Agent": user_agent,
            "Accept": self._get_accept_header(browser_type),
            "Accept-Language": random.choice(self.languages.get(region, self.languages["US"])),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        # Browser-specific headers
        if browser_type == "chrome":
            headers.update({
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": self._get_sec_fetch_site(url, referer),
                "Sec-Fetch-User": "?1",
                "sec-ch-ua": self._get_chrome_ua_string(),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        elif browser_type == "firefox":
            headers.update({
                "DNT": "1",
            })
        elif browser_type == "safari":
            headers.update({
                "DNT": "1",
            })
        elif browser_type == "edge":
            headers.update({
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": self._get_sec_fetch_site(url, referer),
                "Sec-Fetch-User": "?1",
            })
        
        # Add referer
        if referer:
            headers["Referer"] = referer
        elif url:
            headers["Referer"] = self._generate_referer(url)
        
        # Add cache control
        headers["Cache-Control"] = "max-age=0"
        
        return headers
    
    def build_js_headers(self, url: str = "", referer: Optional[str] = None) -> Dict[str, str]:
        """
        Build headers for JavaScript-heavy sites (more browser-like).
        
        Args:
            url: Target URL
            referer: Referer URL
            
        Returns:
            Dict of HTTP headers
        """
        return self.build_headers("chrome", url, referer)
    
    def _get_accept_header(self, browser_type: str) -> str:
        """Get Accept header for browser type."""
        if browser_type == "safari":
            return "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        else:
            return "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
    
    def _get_sec_fetch_site(self, url: str, referer: Optional[str] = None) -> str:
        """Get Sec-Fetch-Site header value."""
        if not referer:
            return "none"
        
        url_domain = urlparse(url).netloc
        referer_domain = urlparse(referer).netloc
        
        if url_domain == referer_domain:
            return "same-origin"
        elif referer_domain in ["www.google.com", "www.bing.com"]:
            return "cross-site"
        else:
            return "same-site"
    
    def _get_chrome_ua_string(self) -> str:
        """Get Chrome sec-ch-ua string."""
        versions = [
            '"Chromium";v="120", "Google Chrome";v="120", "Not_A Brand";v="99"',
            '"Chromium";v="121", "Google Chrome";v="121", "Not_A Brand";v="99"',
            '"Chromium";v="119", "Google Chrome";v="119", "Not_A Brand";v="99"',
        ]
        return random.choice(versions)
    
    def _generate_referer(self, url: str) -> str:
        """Generate realistic referer for URL."""
        domain = urlparse(url).netloc
        
        # Check if we have patterns for this domain
        if domain in self.referer_patterns:
            return random.choice(self.referer_patterns[domain])
        
        # Default to search engine
        return random.choice(["https://www.google.com/", "https://www.bing.com/"])


# Global header builder instance
header_builder = HeaderBuilder()
