"""Deal detector for finding price errors without prior history."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, List, Dict

from src.ingest.category_scanner import DiscoveredProduct

logger = logging.getLogger(__name__)


# Category-specific detection thresholds
CATEGORY_THRESHOLDS: Dict[str, Dict[str, float]] = {
    # High-value electronics - stricter thresholds (price errors are rare)
    "electronics": {
        "min_discount_percent": 35.0,
        "msrp_threshold": 0.65,
        "min_price": 25.0,
        "max_price": 5000.0,
    },
    "computers": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 50.0,
        "max_price": 10000.0,
    },
    "gaming": {
        "min_discount_percent": 25.0,
        "msrp_threshold": 0.75,
        "min_price": 15.0,
        "max_price": 3000.0,
    },
    "tv": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 100.0,
        "max_price": 10000.0,
    },
    # Deals/Clearance pages - already filtered, lower thresholds
    "deals": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 10.0,
        "max_price": 10000.0,
    },
    "clearance": {
        "min_discount_percent": 40.0,
        "msrp_threshold": 0.60,
        "min_price": 5.0,
        "max_price": 10000.0,
    },
    "open-box": {
        "min_discount_percent": 20.0,
        "msrp_threshold": 0.80,
        "min_price": 25.0,
        "max_price": 10000.0,
    },
    "rollback": {
        "min_discount_percent": 25.0,
        "msrp_threshold": 0.75,
        "min_price": 10.0,
        "max_price": 5000.0,
    },
    "special": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 10.0,
        "max_price": 5000.0,
    },
    # Apparel - more generous thresholds (sales are common)
    "apparel": {
        "min_discount_percent": 55.0,
        "msrp_threshold": 0.45,
        "min_price": 10.0,
        "max_price": 1000.0,
    },
    "shoes": {
        "min_discount_percent": 50.0,
        "msrp_threshold": 0.50,
        "min_price": 15.0,
        "max_price": 500.0,
    },
    # Home & Garden
    "home": {
        "min_discount_percent": 40.0,
        "msrp_threshold": 0.60,
        "min_price": 15.0,
        "max_price": 5000.0,
    },
    "kitchen": {
        "min_discount_percent": 40.0,
        "msrp_threshold": 0.60,
        "min_price": 15.0,
        "max_price": 3000.0,
    },
    "appliances": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 50.0,
        "max_price": 10000.0,
    },
    # Tools - Home Depot/Lowe's have lower margins
    "tools": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 15.0,
        "max_price": 3000.0,
    },
    "power tools": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 25.0,
        "max_price": 2000.0,
    },
    # Toys
    "toys": {
        "min_discount_percent": 45.0,
        "msrp_threshold": 0.55,
        "min_price": 10.0,
        "max_price": 500.0,
    },
    "toy": {
        "min_discount_percent": 45.0,
        "msrp_threshold": 0.55,
        "min_price": 10.0,
        "max_price": 500.0,
    },
    # Video Games
    "videogames": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 10.0,
        "max_price": 500.0,
    },
    "video games": {
        "min_discount_percent": 30.0,
        "msrp_threshold": 0.70,
        "min_price": 10.0,
        "max_price": 500.0,
    },
    # Default fallback
    "default": {
        "min_discount_percent": 40.0,
        "msrp_threshold": 0.60,
        "min_price": 1.0,
        "max_price": 10000.0,
    },
}

# Store-specific adjustments (multipliers for thresholds)
STORE_ADJUSTMENTS: Dict[str, Dict[str, float]] = {
    "homedepot": {
        "min_discount_multiplier": 0.85,  # Lower discount threshold for HD
    },
    "lowes": {
        "min_discount_multiplier": 0.85,  # Lower discount threshold for Lowe's
    },
    "costco": {
        "min_discount_multiplier": 0.75,  # Costco already has low prices
    },
    "bestbuy": {
        "min_discount_multiplier": 0.90,  # Best Buy open-box common
    },
    # New retailers
    "newegg": {
        "min_discount_multiplier": 0.80,  # Newegg has frequent flash sales
    },
    "microcenter": {
        "min_discount_multiplier": 0.75,  # Micro Center has competitive prices already
    },
    "gamestop": {
        "min_discount_multiplier": 0.85,  # GameStop clearance and pre-owned common
    },
    "bhphotovideo": {
        "min_discount_multiplier": 0.80,  # B&H has deal zone and open-box
    },
    "kohls": {
        "min_discount_multiplier": 1.10,  # Kohl's always has sales, need higher threshold
    },
    "officedepot": {
        "min_discount_multiplier": 0.90,  # Office Depot moderate discounts
    },
    "ebay": {
        "min_discount_multiplier": 0.85,  # eBay daily deals already discounted
    },
    "macys": {
        "min_discount_multiplier": 1.15,  # Macy's always has sales, need higher threshold
    },
}


@dataclass
class DetectionConfig:
    """Configuration for deal detection."""
    
    msrp_threshold: float = 0.6
    strikethrough_threshold: float = 0.6
    min_discount_percent: float = 40.0
    min_price: Decimal = Decimal("1.00")
    max_price: Decimal = Decimal("10000.00")
    category: Optional[str] = None
    store: Optional[str] = None
    
    @classmethod
    def for_category(cls, category: str, store: Optional[str] = None) -> "DetectionConfig":
        """Get detection config for a specific category and store."""
        # Normalize category name
        category_lower = category.lower() if category else "default"
        
        # Find matching threshold
        thresholds = CATEGORY_THRESHOLDS.get(category_lower)
        
        if not thresholds:
            # Try partial match
            for key, values in CATEGORY_THRESHOLDS.items():
                if key in category_lower or category_lower in key:
                    thresholds = values
                    break
        
        if not thresholds:
            thresholds = CATEGORY_THRESHOLDS["default"]
        
        # Get base values
        min_discount = thresholds.get("min_discount_percent", 40.0)
        
        # Apply store-specific adjustments
        if store and store.lower() in STORE_ADJUSTMENTS:
            adjustments = STORE_ADJUSTMENTS[store.lower()]
            multiplier = adjustments.get("min_discount_multiplier", 1.0)
            min_discount = min_discount * multiplier
        
        return cls(
            msrp_threshold=thresholds.get("msrp_threshold", 0.6),
            strikethrough_threshold=thresholds.get("msrp_threshold", 0.6),
            min_discount_percent=min_discount,
            min_price=Decimal(str(thresholds.get("min_price", 1.0))),
            max_price=Decimal(str(thresholds.get("max_price", 10000.0))),
            category=category,
            store=store,
        )


@dataclass
class DetectedDeal:
    """A detected deal/price error."""
    
    product: DiscoveredProduct
    discount_percent: float
    detection_method: str  # 'msrp', 'strikethrough', 'threshold', 'combined'
    confidence: float
    reason: str
    category: Optional[str] = None
    detection_signals: List[str] = field(default_factory=list)
    
    @property
    def is_significant(self) -> bool:
        """Check if this is a significant deal (worth alerting)."""
        return self.discount_percent >= 40 and self.confidence >= 0.6
    
    @property
    def is_price_error(self) -> bool:
        """Check if this likely a price error (not just a sale)."""
        # High discount + high confidence = likely error
        if self.discount_percent >= 70 and self.confidence >= 0.8:
            return True
        # Multiple detection signals suggest error
        if len(self.detection_signals) >= 2 and self.discount_percent >= 60:
            return True
        return False


class DealDetector:
    """
    Detects deals without requiring prior price history.
    
    Uses multiple methods:
    1. MSRP comparison: Compare current price to MSRP
    2. Strikethrough detection: Compare to displayed "was" price
    3. Percentage threshold: Flag anything above minimum discount
    4. Combined signals: Multiple indicators increase confidence
    """
    
    def __init__(
        self,
        msrp_threshold: float = 0.5,  # Trigger if price <= 50% of MSRP
        strikethrough_threshold: float = 0.5,  # Trigger if 50%+ off strikethrough
        min_discount_percent: float = 50.0,  # Minimum discount to flag
        min_price: Decimal = Decimal("1.00"),  # Ignore items under $1
        max_price: Decimal = Decimal("10000.00"),  # Ignore items over $10k
        config: Optional[DetectionConfig] = None,
    ):
        if config:
            self.msrp_threshold = config.msrp_threshold
            self.strikethrough_threshold = config.strikethrough_threshold
            self.min_discount_percent = config.min_discount_percent
            self.min_price = config.min_price
            self.max_price = config.max_price
            self.category = config.category
        else:
            self.msrp_threshold = msrp_threshold
            self.strikethrough_threshold = strikethrough_threshold
            self.min_discount_percent = min_discount_percent
            self.min_price = min_price
            self.max_price = max_price
            self.category = None
    
    def detect_deal(self, product: DiscoveredProduct) -> Optional[DetectedDeal]:
        """
        Check if a product is a deal worth flagging.
        
        Args:
            product: Discovered product to check
            
        Returns:
            DetectedDeal if deal detected, None otherwise
        """
        if not product.current_price:
            return None
        
        # Price sanity checks
        if product.current_price < self.min_price:
            return None
        if product.current_price > self.max_price:
            return None
        
        # Collect all detection signals
        signals: List[str] = []
        best_deal: Optional[DetectedDeal] = None
        max_discount = 0.0
        
        # 1. Strikethrough price detection (highest confidence)
        strikethrough_deal = self._check_strikethrough(product)
        if strikethrough_deal:
            signals.append("strikethrough")
            if strikethrough_deal.discount_percent > max_discount:
                max_discount = strikethrough_deal.discount_percent
                best_deal = strikethrough_deal
        
        # 2. MSRP comparison (medium confidence)
        msrp_deal = self._check_msrp(product)
        if msrp_deal:
            signals.append("msrp")
            if msrp_deal.discount_percent > max_discount:
                max_discount = msrp_deal.discount_percent
                best_deal = msrp_deal
        
        # If we found deals, enhance with combined signals
        if best_deal and len(signals) > 1:
            # Multiple signals = higher confidence
            combined_confidence = min(1.0, best_deal.confidence + 0.15)
            return DetectedDeal(
                product=product,
                discount_percent=max_discount,
                detection_method="combined",
                confidence=combined_confidence,
                reason=f"{max_discount:.1f}% off (verified by {', '.join(signals)})",
                category=self.category,
                detection_signals=signals,
            )
        
        if best_deal:
            best_deal.detection_signals = signals
            best_deal.category = self.category
        
        return best_deal
    
    def detect_deal_with_config(
        self, 
        product: DiscoveredProduct,
        config: DetectionConfig,
    ) -> Optional[DetectedDeal]:
        """
        Detect deal using specific configuration.
        
        Args:
            product: Product to check
            config: Detection configuration
            
        Returns:
            DetectedDeal if detected, None otherwise
        """
        detector = DealDetector(config=config)
        return detector.detect_deal(product)
    
    def _check_strikethrough(self, product: DiscoveredProduct) -> Optional[DetectedDeal]:
        """Check for deal based on strikethrough/was price."""
        if not product.original_price or product.original_price <= 0:
            return None
        
        if product.current_price >= product.original_price:
            return None
        
        discount_percent = float(
            (1 - product.current_price / product.original_price) * 100
        )
        
        if discount_percent >= self.min_discount_percent:
            confidence = self._calculate_confidence(
                discount_percent,
                has_strikethrough=True,
                has_msrp=bool(product.msrp),
            )
            
            return DetectedDeal(
                product=product,
                discount_percent=discount_percent,
                detection_method="strikethrough",
                confidence=confidence,
                reason=f"{discount_percent:.1f}% off (was ${product.original_price:.2f})",
            )
        
        return None
    
    def _check_msrp(self, product: DiscoveredProduct) -> Optional[DetectedDeal]:
        """Check for deal based on MSRP comparison."""
        if not product.msrp or product.msrp <= 0:
            return None
        
        if product.current_price >= product.msrp:
            return None
        
        discount_percent = float(
            (1 - product.current_price / product.msrp) * 100
        )
        
        ratio = float(product.current_price / product.msrp)
        
        if ratio <= self.msrp_threshold:  # e.g., price is <= 50% of MSRP
            confidence = self._calculate_confidence(
                discount_percent,
                has_strikethrough=bool(product.original_price),
                has_msrp=True,
            )
            
            return DetectedDeal(
                product=product,
                discount_percent=discount_percent,
                detection_method="msrp",
                confidence=confidence,
                reason=f"{discount_percent:.1f}% off MSRP (${product.msrp:.2f})",
            )
        
        return None
    
    def _calculate_confidence(
        self,
        discount_percent: float,
        has_strikethrough: bool,
        has_msrp: bool,
    ) -> float:
        """
        Calculate confidence score for a detected deal.
        
        Higher confidence when:
        - Discount is very high (but not impossibly high)
        - Multiple price reference points available
        """
        confidence = 0.5  # Base confidence
        
        # Adjust based on discount percentage
        if 50 <= discount_percent <= 70:
            confidence += 0.2  # Reasonable discount
        elif 70 < discount_percent <= 85:
            confidence += 0.15  # High discount, might be legit
        elif 85 < discount_percent <= 95:
            confidence += 0.1  # Very high, could be error
        else:  # > 95%
            confidence -= 0.1  # Suspiciously high, might be data error
        
        # Boost if multiple reference points
        if has_strikethrough:
            confidence += 0.15
        if has_msrp:
            confidence += 0.1
        
        # Clamp to valid range
        return max(0.1, min(1.0, confidence))
    
    def detect_deals_batch(
        self, 
        products: List[DiscoveredProduct],
        min_confidence: float = 0.5,
    ) -> List[DetectedDeal]:
        """
        Detect deals in a batch of products.
        
        Args:
            products: List of products to check
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of detected deals sorted by discount percentage
        """
        deals = []
        
        for product in products:
            deal = self.detect_deal(product)
            if deal and deal.confidence >= min_confidence:
                deals.append(deal)
        
        # Sort by discount percentage (highest first)
        deals.sort(key=lambda d: d.discount_percent, reverse=True)
        
        logger.info(
            f"Detected {len(deals)} deals from {len(products)} products "
            f"(min confidence: {min_confidence})"
        )
        
        return deals
    
    def filter_significant_deals(
        self,
        deals: List[DetectedDeal],
        max_results: int = 20,
    ) -> List[DetectedDeal]:
        """
        Filter to only significant deals worth alerting.
        
        Args:
            deals: List of detected deals
            max_results: Maximum number of results to return
            
        Returns:
            Filtered and sorted list of significant deals
        """
        significant = [d for d in deals if d.is_significant]
        
        # Sort by discount percentage
        significant.sort(key=lambda d: d.discount_percent, reverse=True)
        
        return significant[:max_results]


    def detect_deals_for_category(
        self,
        products: List[DiscoveredProduct],
        category_name: str,
        min_confidence: float = 0.5,
    ) -> List[DetectedDeal]:
        """
        Detect deals using category-specific thresholds.
        
        Args:
            products: List of products to check
            category_name: Category name for threshold lookup
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of detected deals
        """
        config = DetectionConfig.for_category(category_name)
        detector = DealDetector(config=config)
        
        deals = []
        for product in products:
            deal = detector.detect_deal(product)
            if deal and deal.confidence >= min_confidence:
                deals.append(deal)
        
        # Sort by discount percentage (highest first)
        deals.sort(key=lambda d: d.discount_percent, reverse=True)
        
        logger.info(
            f"Detected {len(deals)} deals from {len(products)} products "
            f"in category '{category_name}' (thresholds: min_discount={config.min_discount_percent}%)"
        )
        
        return deals
    
    def get_price_error_candidates(
        self,
        deals: List[DetectedDeal],
        max_results: int = 10,
    ) -> List[DetectedDeal]:
        """
        Filter to only potential price errors (not just sales).
        
        Args:
            deals: List of detected deals
            max_results: Maximum number of results
            
        Returns:
            Filtered list of likely price errors
        """
        errors = [d for d in deals if d.is_price_error]
        errors.sort(key=lambda d: (d.confidence, d.discount_percent), reverse=True)
        return errors[:max_results]


def get_detector_for_category(category_name: str) -> DealDetector:
    """Get a DealDetector configured for a specific category."""
    config = DetectionConfig.for_category(category_name)
    return DealDetector(config=config)


# Global deal detector instance with default settings
deal_detector = DealDetector()
