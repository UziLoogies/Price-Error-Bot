"""Canonical product ID mapping utilities per retailer."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CanonicalProductId:
    """Canonical product identifier container."""

    retailer: str
    raw_id: str

    def as_string(self) -> str:
        """Return canonical id string."""
        return f"{self.retailer}:{self.raw_id}"


class ProductIdMapper:
    """Map retailer-specific identifiers to canonical IDs."""

    _id_labels = {
        "amazon_us": "asin",
        "walmart": "item_id",
        "target": "tcin",
        "bestbuy": "sku",
        "costco": "item_id",
        "newegg": "item_number",
        "macys": "product_id",
        "homedepot": "sku",
        "lowes": "item_id",
        "microcenter": "product_id",
        "gamestop": "sku",
        "bhphotovideo": "product_id",
        "kohls": "product_id",
        "officedepot": "sku",
        "ebay": "item_id",
    }

    _patterns = {
        "amazon_us": [
            r"/dp/([A-Z0-9]{10})",
            r"/gp/product/([A-Z0-9]{10})",
            r"/product/([A-Z0-9]{10})",
        ],
        "walmart": [
            r"/ip/(\d+)",
            r"[?&]itemId=(\d+)",
        ],
        "target": [
            r"/A-(\d+)",
            r"[?&]preselect=(\d+)",
        ],
        "bestbuy": [
            r"/site/[^/]+/(\d+)\.p",
            r"[?&]skuId=(\d+)",
        ],
        "costco": [
            r"\.product\.(\d+)\.html",
            r"[?&]productId=(\d+)",
        ],
        "newegg": [
            r"/p/([A-Z0-9\-]+)",
            r"[?&]Item=([A-Z0-9\-]+)",
        ],
        "macys": [
            r"/shop/product/[^/]+/([0-9]+)",
            r"[?&]ID=(\d+)",
        ],
        "homedepot": [
            r"/p/[^/]+/(\d+)",
        ],
        "lowes": [
            r"/pd/[^/]+/(\d+)",
            r"[?&]productId=(\d+)",
        ],
        "microcenter": [
            r"/product/(\d+)",
        ],
        "gamestop": [
            r"/p/(\d+)",
            r"[?&]sku=(\d+)",
        ],
        "bhphotovideo": [
            r"/c/product/(\d+)-",
            r"[?&]sku=(\d+)",
        ],
        "kohls": [
            r"/product/prd-(\d+)",
            r"[?&]prdPV=(\d+)",
        ],
        "officedepot": [
            r"/catalog/catalogSku\.do\?id=(\d+)",
            r"[?&]sku=(\d+)",
        ],
        "ebay": [
            r"/itm/(\d+)",
            r"[?&]item=(\d+)",
        ],
    }

    def canonicalize(
        self,
        retailer: str,
        product_id: Optional[str] = None,
        url: Optional[str] = None,
    ) -> CanonicalProductId:
        """
        Build canonical product id for a retailer.

        Args:
            retailer: Store identifier
            product_id: Raw product ID (ASIN/TCIN/SKU/etc.)
            url: Optional product URL for extraction
        """
        retailer = (retailer or "").lower()
        raw_id = product_id or self.extract_product_id(retailer, url)

        if not raw_id:
            raw_id = self._fallback_from_url(url)
            logger.debug("Falling back to hashed id for %s", retailer)

        return CanonicalProductId(retailer=retailer, raw_id=raw_id)

    def extract_product_id(self, retailer: str, url: Optional[str]) -> Optional[str]:
        """Extract product ID from a URL using retailer patterns."""
        if not retailer or not url:
            return None
        patterns = self._patterns.get(retailer.lower(), [])
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def split_canonical_id(self, canonical_id: str) -> tuple[Optional[str], Optional[str]]:
        """Split canonical id string into (retailer, raw_id)."""
        if not canonical_id or ":" not in canonical_id:
            return None, None
        retailer, raw_id = canonical_id.split(":", 1)
        return retailer, raw_id

    def id_label(self, retailer: str) -> str:
        """Return label describing the id type (asin/sku/etc.)."""
        return self._id_labels.get(retailer.lower(), "product_id")

    @staticmethod
    def _fallback_from_url(url: Optional[str]) -> str:
        """Create a stable fallback id from URL."""
        if not url:
            return "unknown"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return digest[:16]


product_id_mapper = ProductIdMapper()
