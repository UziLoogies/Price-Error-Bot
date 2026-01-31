"""Filtering system for scan results."""

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Set

from src.ingest.category_scanner import DiscoveredProduct
from src.config import settings

logger = logging.getLogger(__name__)


def _parse_csv_values(value: Optional[str]) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


_KIDS_KEYWORDS = _parse_csv_values(settings.kids_exclude_keywords)
_KIDS_KEYWORD_PATTERNS = [
    re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
    for keyword in _KIDS_KEYWORDS
]
_KIDS_LOW_PRICE_MAX = (
    Decimal(str(settings.kids_low_price_max))
    if getattr(settings, "kids_low_price_max", 0) and settings.kids_low_price_max > 0
    else None
)
_WALMART_KIDS_SKUS = set(_parse_csv_values(settings.kids_exclude_skus_walmart))


def _is_kids_keyword_match(text: str) -> bool:
    if not _KIDS_KEYWORD_PATTERNS:
        return False
    return any(pattern.search(text) for pattern in _KIDS_KEYWORD_PATTERNS)


def is_low_cost_kids_item(product: DiscoveredProduct) -> bool:
    """Return True if the product matches kids keywords under the low-price threshold."""
    if _KIDS_LOW_PRICE_MAX is None:
        return False
    if product.current_price is None:
        return False
    if product.current_price > _KIDS_LOW_PRICE_MAX:
        return False
    text = f"{product.title} {product.sku}".lower()
    return _is_kids_keyword_match(text)


def filter_low_cost_kids_items(products: List[DiscoveredProduct]) -> List[DiscoveredProduct]:
    """Filter out low-cost kids items using keyword + price rules and explicit SKUs."""
    if not products:
        return products

    filtered: List[DiscoveredProduct] = []
    removed_by_sku = 0
    removed_by_rule = 0

    for product in products:
        if product.store == "walmart" and product.sku in _WALMART_KIDS_SKUS:
            removed_by_sku += 1
            continue
        if is_low_cost_kids_item(product):
            removed_by_rule += 1
            continue
        filtered.append(product)

    total_removed = removed_by_sku + removed_by_rule
    if total_removed:
        logger.info(
            "Filtered low-cost kids items: %s removed (%s explicit SKUs, %s keyword+price).",
            total_removed,
            removed_by_sku,
            removed_by_rule,
        )

    return filtered


@dataclass
class FilterConfig:
    """Configuration for filtering discovered products."""
    
    keywords: List[str] = field(default_factory=list)  # Include if matches any
    exclude_keywords: List[str] = field(default_factory=list)  # Exclude if matches any
    brands: List[str] = field(default_factory=list)  # Include only these brands
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    excluded_skus: Set[str] = field(default_factory=set)
    excluded_brands: Set[str] = field(default_factory=set)
    
    @classmethod
    def from_json_fields(
        cls,
        keywords_json: Optional[str] = None,
        exclude_keywords_json: Optional[str] = None,
        brands_json: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
    ) -> "FilterConfig":
        """Create FilterConfig from JSON string fields (as stored in DB)."""
        keywords = []
        exclude_keywords = []
        brands = []
        
        if keywords_json:
            try:
                keywords = json.loads(keywords_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid keywords JSON: {keywords_json}")
        
        if exclude_keywords_json:
            try:
                exclude_keywords = json.loads(exclude_keywords_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid exclude_keywords JSON: {exclude_keywords_json}")
        
        if brands_json:
            try:
                brands = json.loads(brands_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid brands JSON: {brands_json}")
        
        return cls(
            keywords=keywords,
            exclude_keywords=exclude_keywords,
            brands=brands,
            min_price=min_price,
            max_price=max_price,
        )


class ProductFilter:
    """Filters discovered products based on various criteria."""
    
    def __init__(self, config: FilterConfig):
        self.config = config
        
        # Compile keyword patterns for efficiency
        self._include_patterns = [
            re.compile(kw, re.IGNORECASE) 
            for kw in config.keywords if kw
        ]
        self._exclude_patterns = [
            re.compile(kw, re.IGNORECASE) 
            for kw in config.exclude_keywords if kw
        ]
        self._brand_patterns = [
            re.compile(re.escape(brand), re.IGNORECASE) 
            for brand in config.brands if brand
        ]
        self._excluded_brand_patterns = [
            re.compile(re.escape(brand), re.IGNORECASE)
            for brand in config.excluded_brands if brand
        ]
    
    def matches_keywords(self, product: DiscoveredProduct) -> bool:
        """Check if product matches include keywords."""
        if not self._include_patterns:
            return True  # No keyword filter = include all
        
        text = f"{product.title} {product.sku}"
        return any(pattern.search(text) for pattern in self._include_patterns)
    
    def matches_exclude_keywords(self, product: DiscoveredProduct) -> bool:
        """Check if product matches any exclude keywords."""
        if not self._exclude_patterns:
            return False  # No exclude patterns = don't exclude
        
        text = f"{product.title} {product.sku}"
        return any(pattern.search(text) for pattern in self._exclude_patterns)
    
    def matches_brand(self, product: DiscoveredProduct) -> bool:
        """Check if product matches allowed brands."""
        if not self._brand_patterns:
            return True  # No brand filter = include all
        
        return any(pattern.search(product.title) for pattern in self._brand_patterns)
    
    def is_excluded_brand(self, product: DiscoveredProduct) -> bool:
        """Check if product is from an excluded brand."""
        if not self._excluded_brand_patterns:
            return False
        
        return any(pattern.search(product.title) for pattern in self._excluded_brand_patterns)
    
    def matches_price_range(self, product: DiscoveredProduct) -> bool:
        """Check if product price is within allowed range."""
        if product.current_price is None:
            return True  # Can't filter without price
        
        if self.config.min_price and product.current_price < self.config.min_price:
            return False
        
        if self.config.max_price and product.current_price > self.config.max_price:
            return False
        
        return True
    
    def is_excluded_sku(self, product: DiscoveredProduct) -> bool:
        """Check if product SKU is in exclusion list."""
        if not self.config.excluded_skus:
            return False
        
        return product.sku in self.config.excluded_skus
    
    def should_include(self, product: DiscoveredProduct) -> bool:
        """
        Determine if a product should be included after all filters.
        
        Returns:
            True if product passes all filters, False otherwise
        """
        # Check exclusions first (most specific)
        if self.is_excluded_sku(product):
            logger.debug(f"Filtered out {product.sku}: excluded SKU")
            return False
        
        if self.matches_exclude_keywords(product):
            logger.debug(f"Filtered out {product.sku}: matches exclude keyword")
            return False
        
        if self.is_excluded_brand(product):
            logger.debug(f"Filtered out {product.sku}: excluded brand")
            return False
        
        # Check inclusion criteria
        if not self.matches_keywords(product):
            logger.debug(f"Filtered out {product.sku}: doesn't match keywords")
            return False
        
        if not self.matches_brand(product):
            logger.debug(f"Filtered out {product.sku}: doesn't match brand filter")
            return False
        
        if not self.matches_price_range(product):
            logger.debug(f"Filtered out {product.sku}: outside price range")
            return False
        
        return True
    
    def filter_products(
        self, 
        products: List[DiscoveredProduct]
    ) -> List[DiscoveredProduct]:
        """
        Filter a list of products.
        
        Args:
            products: List of products to filter
            
        Returns:
            Filtered list of products
        """
        original_count = len(products)
        filtered = [p for p in products if self.should_include(p)]
        
        logger.info(
            f"Filtered products: {len(filtered)}/{original_count} passed "
            f"(removed {original_count - len(filtered)})"
        )
        
        return filtered


class ExclusionManager:
    """Manages product exclusion list from database."""
    
    def __init__(self):
        self._excluded_skus: dict[str, Set[str]] = {}  # store -> set of SKUs
        self._excluded_keywords: dict[str, List[re.Pattern]] = {}
        self._excluded_brands: dict[str, Set[str]] = {}
        self._loaded = False
    
    async def load_exclusions(self, db):
        """Load exclusions from database."""
        from sqlalchemy import select
        from src.db.models import ProductExclusion
        
        result = await db.execute(
            select(ProductExclusion).where(ProductExclusion.enabled == True)
        )
        exclusions = result.scalars().all()
        
        # Reset collections
        self._excluded_skus = {}
        self._excluded_keywords = {}
        self._excluded_brands = {}
        
        for exc in exclusions:
            store = exc.store
            
            # Initialize store collections if needed
            if store not in self._excluded_skus:
                self._excluded_skus[store] = set()
            if store not in self._excluded_keywords:
                self._excluded_keywords[store] = []
            if store not in self._excluded_brands:
                self._excluded_brands[store] = set()
            
            # Add exclusion based on type
            if exc.sku:
                self._excluded_skus[store].add(exc.sku)
            if exc.keyword:
                try:
                    self._excluded_keywords[store].append(
                        re.compile(exc.keyword, re.IGNORECASE)
                    )
                except re.error:
                    logger.warning(f"Invalid exclusion regex: {exc.keyword}")
            if exc.brand:
                self._excluded_brands[store].add(exc.brand.lower())
        
        self._loaded = True
        logger.info(f"Loaded {len(exclusions)} product exclusions")
    
    def get_excluded_skus(self, store: str) -> Set[str]:
        """Get excluded SKUs for a store."""
        return self._excluded_skus.get(store, set()) | self._excluded_skus.get("*", set())
    
    def get_excluded_brands(self, store: str) -> Set[str]:
        """Get excluded brands for a store."""
        return self._excluded_brands.get(store, set()) | self._excluded_brands.get("*", set())
    
    def is_excluded(self, product: DiscoveredProduct) -> bool:
        """Check if a product is excluded."""
        store = product.store
        
        # Check SKU exclusion
        excluded_skus = self.get_excluded_skus(store)
        if product.sku in excluded_skus:
            return True
        
        # Check keyword exclusion
        keywords = self._excluded_keywords.get(store, []) + self._excluded_keywords.get("*", [])
        text = f"{product.title} {product.sku}"
        for pattern in keywords:
            if pattern.search(text):
                return True
        
        # Check brand exclusion
        excluded_brands = self.get_excluded_brands(store)
        title_lower = product.title.lower()
        for brand in excluded_brands:
            if brand in title_lower:
                return True
        
        return False


# Global exclusion manager instance
exclusion_manager = ExclusionManager()


# Enhanced filtering with MSRP context and category-specific rules

async def filter_with_msrp_context(
    product: DiscoveredProduct,
    product_db_obj=None,
    is_clearance: bool = False,
) -> tuple[bool, Optional[str]]:
    """
    Filter product using MSRP context.
    
    Args:
        product: Discovered product
        product_db_obj: Optional Product database object
        is_clearance: Whether product is in clearance section
        
    Returns:
        Tuple of (should_include: bool, reason: str or None)
    """
    from src.detect.msrp_service import msrp_service
    
    if not product_db_obj:
        return True, None
    
    # Get MSRP
    msrp = await msrp_service.get_msrp(product_db_obj)
    if not msrp or msrp <= 0:
        return True, None  # No MSRP available, can't filter
    
    # Calculate discount from MSRP
    if product.current_price and product.current_price > 0:
        discount = float((1 - product.current_price / msrp) * 100)
        
        # Flag if >90% off MSRP (unless clearance)
        if discount >= 90.0 and not is_clearance:
            return False, f"{discount:.1f}% off MSRP (${msrp:.2f}) - potential error"
    
    return True, None


def get_category_specific_rules(category_name: str) -> Dict[str, float]:
    """
    Get category-specific filtering rules.
    
    Args:
        category_name: Category name
        
    Returns:
        Dict with category-specific thresholds
    """
    from src.detect.deal_detector import CATEGORY_THRESHOLDS
    
    category_lower = category_name.lower()
    
    # Check for exact match
    if category_lower in CATEGORY_THRESHOLDS:
        return CATEGORY_THRESHOLDS[category_lower]
    
    # Check for partial match
    for cat_key, rules in CATEGORY_THRESHOLDS.items():
        if cat_key in category_lower or category_lower in cat_key:
            return rules
    
    # Default rules
    return {
        "min_discount_percent": 40.0,
        "msrp_threshold": 0.60,
        "min_price": 10.0,
        "max_price": 10000.0,
    }


def is_clearance_section(category_name: str, url: str) -> bool:
    """
    Detect if category is a clearance section.
    
    Args:
        category_name: Category name
        url: Category URL
        
    Returns:
        True if appears to be clearance section
    """
    text = f"{category_name} {url}".lower()
    clearance_keywords = [
        "clearance",
        "closeout",
        "final sale",
        "liquidation",
        "overstock",
    ]
    return any(keyword in text for keyword in clearance_keywords)


async def apply_enhanced_filtering(
    product: DiscoveredProduct,
    category_name: Optional[str] = None,
    product_db_obj=None,
) -> tuple[bool, Optional[str]]:
    """
    Apply enhanced filtering with MSRP context and category-specific rules.
    
    Args:
        product: Discovered product
        category_name: Category name
        product_db_obj: Optional Product database object
        
    Returns:
        Tuple of (should_include: bool, reason: str or None)
    """
    # Check if clearance section (allow deeper discounts)
    is_clearance = False
    if category_name:
        is_clearance = is_clearance_section(category_name, product.url or "")
    
    # Apply MSRP-based filtering
    if product_db_obj:
        should_include, reason = await filter_with_msrp_context(
            product,
            product_db_obj,
            is_clearance,
        )
        if not should_include:
            return False, reason
    
    # Apply category-specific rules
    if category_name:
        rules = get_category_specific_rules(category_name)
        
        # Check price range
        if product.current_price:
            if rules.get("min_price") and product.current_price < Decimal(str(rules["min_price"])):
                return False, f"Price ${product.current_price:.2f} below category minimum ${rules['min_price']:.2f}"
            
            if rules.get("max_price") and product.current_price > Decimal(str(rules["max_price"])):
                return False, f"Price ${product.current_price:.2f} above category maximum ${rules['max_price']:.2f}"
    
    return True, None