"""Base fetcher interface for price data sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class RawPriceData:
    """Raw price data from a source."""

    sku: str
    url: str
    store: str
    current_price: Optional[Decimal]
    msrp: Optional[Decimal]
    shipping: Decimal = Decimal("0.00")
    availability: str = "unknown"
    currency: str = "USD"
    title: Optional[str] = None
    confidence: float = 1.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for a fetcher."""

    requests_per_second: float = 1.0
    burst_size: int = 5
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 60.0


class BaseFetcher(ABC):
    """Abstract base class for price fetchers."""

    @abstractmethod
    async def fetch(self, identifier: str) -> RawPriceData:
        """
        Fetch price data for a product.

        Args:
            identifier: Product identifier (ASIN for Amazon, SKU for others)

        Returns:
            RawPriceData object with price information

        Raises:
            FetcherError: If fetch fails
        """
        pass

    @abstractmethod
    def get_rate_limit(self) -> RateLimitConfig:
        """Get rate limiting configuration for this fetcher."""
        pass

    @abstractmethod
    def get_store_name(self) -> str:
        """Get the store name (e.g., 'amazon_us')."""
        pass
