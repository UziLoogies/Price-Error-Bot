"""Normalize raw price data and filter outliers."""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.ingest.base import RawPriceData

logger = logging.getLogger(__name__)


@dataclass
class NormalizedPrice:
    """Canonical normalized price data."""

    sku: str
    url: str
    store: str
    current_price: Decimal
    msrp: Decimal | None
    previous_price: Decimal | None
    shipping: Decimal
    availability: str  # "in_stock", "out_of_stock", "preorder"
    currency: str
    timestamp: datetime
    confidence: float  # 0.0 - 1.0
    title: str | None = None


class NormalizationError(Exception):
    """Raised when normalization fails."""

    pass


class PriceNormalizer:
    """Normalize and validate price data."""

    # Price patterns that indicate errors or placeholders
    INVALID_PRICES = {
        Decimal("0.00"),
        Decimal("0.0"),
        Decimal("0"),
    }

    # Keywords that indicate unavailable prices
    UNAVAILABLE_KEYWORDS = [
        "see price in cart",
        "see price at checkout",
        "contact us",
        "price unavailable",
    ]

    def normalize(self, raw: RawPriceData, previous_price: Decimal | None = None) -> NormalizedPrice:
        """
        Normalize raw price data.

        Args:
            raw: Raw price data from fetcher
            previous_price: Previous known price for comparison

        Returns:
            NormalizedPrice object

        Raises:
            NormalizationError: If price data is invalid
        """
        # Validate price
        if raw.current_price is None:
            raise NormalizationError(f"No price found for {raw.sku}")

        # Check for invalid price values
        if raw.current_price in self.INVALID_PRICES:
            raise NormalizationError(f"Invalid price $0.00 for {raw.sku}")

        # Check for negative prices
        if raw.current_price < 0:
            raise NormalizationError(f"Negative price {raw.current_price} for {raw.sku}")

        # Check title for unavailable keywords
        confidence = raw.confidence
        if raw.title:
            title_lower = raw.title.lower()
            for keyword in self.UNAVAILABLE_KEYWORDS:
                if keyword in title_lower:
                    confidence = min(confidence, 0.3)
                    logger.warning(
                        f"Low confidence price for {raw.sku}: "
                        f"title contains '{keyword}'"
                    )

        # Normalize availability
        availability = self._normalize_availability(raw.availability)

        # Validate stock status for alerting
        if availability == "out_of_stock" and raw.current_price:
            # OOS pages might return placeholder prices
            confidence = min(confidence, 0.5)
            logger.warning(
                f"Price found for OOS product {raw.sku}, "
                "lowering confidence"
            )

        # Ensure shipping is set
        shipping = raw.shipping if raw.shipping is not None else Decimal("0.00")

        # Currency normalization (future: currency conversion)
        currency = raw.currency.upper() if raw.currency else "USD"

        return NormalizedPrice(
            sku=raw.sku,
            url=raw.url,
            store=raw.store,
            current_price=raw.current_price,
            msrp=raw.msrp,
            previous_price=previous_price,
            shipping=shipping,
            availability=availability,
            currency=currency,
            timestamp=raw.timestamp,
            confidence=confidence,
            title=raw.title,
        )

    def _normalize_availability(self, availability: str) -> str:
        """Normalize availability string to canonical values."""
        if not availability:
            return "unknown"

        avail_lower = availability.lower()

        if "in_stock" in avail_lower or "available" in avail_lower:
            return "in_stock"
        elif "out_of_stock" in avail_lower or "unavailable" in avail_lower:
            return "out_of_stock"
        elif "preorder" in avail_lower or "pre-order" in avail_lower:
            return "preorder"
        else:
            return "unknown"
