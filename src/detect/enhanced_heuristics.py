"""Enhanced heuristic rules for price error detection.

Implements advanced heuristics including penny pricing detection,
currency conversion errors, variant price discrepancies, and category outliers.
"""

import logging
import re
from decimal import Decimal
from typing import Optional, List, Dict

from src.detect.msrp_service import msrp_service
from src.detect.comparative_pricing import comparative_pricing_engine

logger = logging.getLogger(__name__)


class EnhancedHeuristics:
    """
    Enhanced heuristic rules for price error detection.
    
    Features:
    - Penny pricing detection
    - Currency conversion error detection
    - Variant price discrepancy detection
    - Category outlier detection
    - MSRP deviation detection
    """
    
    def __init__(self):
        """Initialize enhanced heuristics."""
        self.penny_pricing_max = Decimal("1.00")
        self.high_value_threshold = Decimal("50.00")
    
    def detect_penny_pricing(
        self,
        current_price: Decimal,
        msrp: Optional[Decimal] = None,
        baseline_price: Optional[Decimal] = None,
    ) -> tuple[bool, str]:
        """
        Detect penny pricing errors ($0.01-$1.00 for high-value items).
        
        Args:
            current_price: Current price
            msrp: MSRP if available
            baseline_price: Baseline price if available
            
        Returns:
            Tuple of (is_error: bool, reason: str)
        """
        if current_price > self.penny_pricing_max:
            return False, ""
        
        # Check if this is a high-value item
        expected_price = msrp or baseline_price
        if expected_price and expected_price >= self.high_value_threshold:
            return True, f"Penny pricing: ${current_price:.2f} for item expected ${expected_price:.2f}"
        
        return False, ""
    
    def detect_currency_error(
        self,
        price_text: str,
        current_price: Decimal,
        msrp: Optional[Decimal] = None,
    ) -> tuple[bool, str]:
        """
        Detect currency conversion errors (e.g., $19.99 MXN).
        
        Args:
            price_text: Original price text from page
            current_price: Parsed current price
            msrp: MSRP if available
            
        Returns:
            Tuple of (is_error: bool, reason: str)
        """
        # Check for currency indicators in text
        currency_patterns = [
            r'\$\d+\.\d+\s*(MXN|CAD|EUR|GBP|JPY)',
            r'\d+\.\d+\s*(pesos|euros|pounds|yen)',
        ]
        
        for pattern in currency_patterns:
            if re.search(pattern, price_text, re.IGNORECASE):
                return True, f"Currency error detected in price text: {price_text}"
        
        # Check for suspicious price ratios (might be currency conversion)
        if msrp and msrp > 0:
            ratio = current_price / msrp
            # If price is exactly 1/100th or 1/20th of MSRP, might be currency error
            if abs(ratio - Decimal("0.01")) < Decimal("0.001") or abs(ratio - Decimal("0.05")) < Decimal("0.001"):
                return True, f"Possible currency conversion error: ${current_price:.2f} vs MSRP ${msrp:.2f}"
        
        return False, ""
    
    async def detect_variant_discrepancy(
        self,
        product_sku: str,
        current_price: Decimal,
        store: str,
    ) -> tuple[bool, str]:
        """
        Detect price discrepancies across product variants.
        
        Args:
            product_sku: Product SKU (base SKU, variants share prefix)
            current_price: Current price
            store: Store identifier
            
        Returns:
            Tuple of (is_error: bool, reason: str)
        """
        # This would require fetching other variants
        # For now, return False (can be enhanced with variant detection)
        return False, ""
    
    async def detect_category_outlier(
        self,
        current_price: Decimal,
        category: str,
        store: str,
    ) -> tuple[bool, str]:
        """
        Detect if price is >3σ below category average.
        
        Args:
            current_price: Current price
            category: Category name
            store: Store identifier
            
        Returns:
            Tuple of (is_error: bool, reason: str)
        """
        # Use comparative pricing engine for category average
        comparison = await comparative_pricing_engine.compare_price(
            current_price,
            "",  # SKU not needed for category comparison
            category,
        )
        
        if comparison.z_score is not None and comparison.z_score < -3.0:
            return True, (
                f"Category outlier: ${current_price:.2f} is "
                f"{abs(comparison.z_score):.1f}σ below category average "
                f"${comparison.market_average:.2f}"
            )
        
        return False, ""
    
    async def detect_msrp_deviation(
        self,
        current_price: Decimal,
        product,
        is_clearance: bool = False,
    ) -> tuple[bool, str]:
        """
        Detect >90% off MSRP (unless marked clearance).
        
        Args:
            current_price: Current price
            product: Product object
            is_clearance: Whether product is in clearance section
            
        Returns:
            Tuple of (is_error: bool, reason: str)
        """
        if is_clearance:
            return False, ""  # Allow deeper discounts in clearance
        
        is_anomalous = await msrp_service.is_anomalous_msrp_discount(current_price, product)
        if is_anomalous:
            msrp = await msrp_service.get_msrp(product)
            if msrp:
                discount = await msrp_service.calculate_msrp_discount(current_price, msrp)
                return True, f"{discount:.1f}% off MSRP (${msrp:.2f}) - potential error"
        
        return False, ""
    
    async def apply_all_heuristics(
        self,
        current_price: Decimal,
        price_text: str,
        product,
        category: Optional[str] = None,
        is_clearance: bool = False,
    ) -> List[tuple[str, str]]:
        """
        Apply all enhanced heuristics and return detected issues.
        
        Args:
            current_price: Current price
            price_text: Original price text
            product: Product object
            category: Category name
            is_clearance: Whether in clearance section
            
        Returns:
            List of (heuristic_name, reason) tuples
        """
        issues = []
        
        # Penny pricing
        is_penny, reason = self.detect_penny_pricing(
            current_price,
            product.msrp,
            product.baseline_price,
        )
        if is_penny:
            issues.append(("penny_pricing", reason))
        
        # Currency error
        is_currency, reason = self.detect_currency_error(
            price_text,
            current_price,
            product.msrp,
        )
        if is_currency:
            issues.append(("currency_error", reason))
        
        # MSRP deviation
        is_msrp, reason = await self.detect_msrp_deviation(
            current_price,
            product,
            is_clearance,
        )
        if is_msrp:
            issues.append(("msrp_deviation", reason))
        
        # Category outlier
        if category:
            is_outlier, reason = await self.detect_category_outlier(
                current_price,
                category,
                product.store,
            )
            if is_outlier:
                issues.append(("category_outlier", reason))
        
        return issues


# Global enhanced heuristics instance
enhanced_heuristics = EnhancedHeuristics()
