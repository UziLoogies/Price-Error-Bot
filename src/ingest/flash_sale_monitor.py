"""Flash sale monitor for limited-time offers.

Identifies flash sale sections on category pages and monitors
limited-time offers with increased scan frequency.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

from src.ingest.category_scanner import DiscoveredProduct

logger = logging.getLogger(__name__)


class FlashSaleMonitor:
    """
    Monitors flash sales and limited-time offers.
    
    Features:
    - Identify flash sale sections on category pages
    - Monitor limited-time offers
    - Increase scan frequency for flash sale items
    - Track sale end times
    """
    
    def __init__(self):
        """Initialize flash sale monitor."""
        self.flash_sale_keywords = [
            "flash sale",
            "limited time",
            "today only",
            "24 hour sale",
            "daily deal",
            "lightning deal",
            "deal of the day",
            "time limited",
            "ending soon",
        ]
    
    def is_flash_sale_section(self, category_name: str, url: str) -> bool:
        """
        Detect if a category is a flash sale section.
        
        Args:
            category_name: Category name
            url: Category URL
            
        Returns:
            True if appears to be flash sale section
        """
        text = f"{category_name} {url}".lower()
        return any(keyword in text for keyword in self.flash_sale_keywords)
    
    def detect_flash_sale_products(
        self,
        products: List[DiscoveredProduct],
        page_content: Optional[str] = None,
    ) -> List[DiscoveredProduct]:
        """
        Identify products that appear to be in a flash sale.
        
        Args:
            products: List of discovered products
            page_content: Optional HTML content for analysis
            
        Returns:
            List of products that appear to be flash sale items
        """
        flash_sale_products = []
        
        # Check product titles/descriptions for flash sale indicators
        for product in products:
            title_lower = (product.title or "").lower()
            
            # Check for time-limited indicators
            time_indicators = [
                "ends in",
                "expires",
                "limited time",
                "today only",
                "flash sale",
            ]
            
            if any(indicator in title_lower for indicator in time_indicators):
                flash_sale_products.append(product)
        
        return flash_sale_products
    
    def get_scan_priority_boost(self, is_flash_sale: bool) -> float:
        """
        Get priority boost for flash sale items.
        
        Args:
            is_flash_sale: Whether item is in flash sale
            
        Returns:
            Priority multiplier
        """
        if is_flash_sale:
            return 2.0  # Double priority for flash sales
        return 1.0
    
    def get_scan_interval_minutes(self, is_flash_sale: bool, base_interval: int) -> int:
        """
        Get adjusted scan interval for flash sale items.
        
        Args:
            is_flash_sale: Whether item is in flash sale
            base_interval: Base scan interval in minutes
            
        Returns:
            Adjusted interval in minutes
        """
        if is_flash_sale:
            # Scan flash sales every minute
            return min(1, base_interval)
        return base_interval


# Global flash sale monitor instance
flash_sale_monitor = FlashSaleMonitor()
