"""Focused scanner for high-value targets.

Targets high-value categories more frequently, skips unchanged pages,
scans new arrivals first, and prioritizes clearance/deal sections.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from src.ingest.smart_cache import smart_cache
from src.ingest.http_cache import http_cache

logger = logging.getLogger(__name__)


class FocusedScanner:
    """
    Focuses scanning on high-value targets.
    
    Features:
    - Target high-value categories more frequently
    - Skip unchanged pages (via ETag/Last-Modified)
    - Scan new arrivals first
    - Prioritize clearance/deal sections
    """
    
    def __init__(self):
        """Initialize focused scanner."""
        # High-value category keywords
        self.high_value_keywords = [
            "electronics",
            "computers",
            "gaming",
            "laptops",
            "tablets",
            "phones",
            "cameras",
            "tvs",
            "monitors",
        ]
        
        # Deal section keywords
        self.deal_section_keywords = [
            "clearance",
            "deal",
            "sale",
            "discount",
            "outlet",
            "bargain",
        ]
    
    def is_high_value_category(self, category_name: str) -> bool:
        """
        Check if category is high-value.
        
        Args:
            category_name: Category name
            
        Returns:
            True if high-value
        """
        category_lower = category_name.lower()
        return any(keyword in category_lower for keyword in self.high_value_keywords)
    
    def is_deal_section(self, category_name: str, url: str) -> bool:
        """
        Check if category is a deal/clearance section.
        
        Args:
            category_name: Category name
            url: Category URL
            
        Returns:
            True if deal section
        """
        text = f"{category_name} {url}".lower()
        return any(keyword in text for keyword in self.deal_section_keywords)
    
    async def should_scan_category(
        self,
        category: Dict[str, Any],
        last_scan: Optional[datetime] = None,
    ) -> bool:
        """
        Determine if category should be scanned based on focus criteria.
        
        Args:
            category: Category data
            last_scan: Last scan time
            
        Returns:
            True if should scan
        """
        category_name = category.get("category_name", "")
        
        # Always scan high-value categories
        if self.is_high_value_category(category_name):
            return True
        
        # Always scan deal sections
        if self.is_deal_section(category_name, category.get("category_url", "")):
            return True
        
        # For other categories, check if recently scanned
        if last_scan:
            hours_since = (datetime.utcnow() - last_scan).total_seconds() / 3600
            # Scan less frequently for low-value categories
            return hours_since >= 6  # At least 6 hours since last scan
        
        return True  # Never scanned, scan it
    
    async def get_scan_priority(
        self,
        category: Dict[str, Any],
    ) -> float:
        """
        Get scan priority for category.
        
        Args:
            category: Category data
            
        Returns:
            Priority score (higher = more important)
        """
        priority = float(category.get("priority", 5))
        category_name = category.get("category_name", "")
        
        # Boost for high-value categories
        if self.is_high_value_category(category_name):
            priority += 3.0
        
        # Boost for deal sections
        if self.is_deal_section(category_name, category.get("category_url", "")):
            priority += 2.0
        
        # Boost for categories with recent deals
        deals_found = category.get("deals_found", 0)
        if deals_found >= 5:
            priority += 2.0
        elif deals_found > 0:
            priority += 1.0
        
        return priority
    
    async def filter_unchanged_pages(
        self,
        urls: List[str],
        category: str = "",
    ) -> List[str]:
        """
        Filter out URLs that haven't changed (using cache).
        
        Args:
            urls: List of URLs to check
            category: Category name
            
        Returns:
            List of URLs that need scanning
        """
        if not settings.http_cache_enabled:
            return urls
        
        changed_urls = []
        
        for url in urls:
            # Check if should refresh
            should_refresh = await smart_cache.should_refresh(
                url,
                priority="high" if self.is_high_value_category(category) else "normal",
                category=category,
            )
            
            if should_refresh:
                changed_urls.append(url)
            else:
                # Check if content has changed
                cached_content = await http_cache.get_cached_content(url)
                if cached_content:
                    # Content exists and is fresh, skip
                    logger.debug(f"Skipping unchanged page: {url}")
                    continue
                changed_urls.append(url)
        
        return changed_urls
    
    def prioritize_urls(
        self,
        urls: List[str],
        category_name: str = "",
    ) -> List[str]:
        """
        Prioritize URLs for scanning (new arrivals first, then by page number).
        
        Args:
            urls: List of URLs
            category_name: Category name
            
        Returns:
            Prioritized list of URLs
        """
        # For now, just return as-is
        # Could add logic to detect "new arrivals" URLs and prioritize them
        return urls


# Global focused scanner instance
focused_scanner = FocusedScanner()
