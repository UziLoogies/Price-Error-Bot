"""Deduplication and cooldown logic for alerts."""

import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)


class DedupeManager:
    """Manages alert deduplication and cooldown."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self.dedupe_ttl_hours = settings.dedupe_ttl_hours
        self.cooldown_minutes = settings.cooldown_minutes

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    def _get_dedupe_key(self, store: str, sku: str, price_bucket: Decimal) -> str:
        """
        Generate dedupe key for an alert.

        Price is rounded to nearest dollar to avoid micro-fluctuation spam.

        Args:
            store: Store name
            sku: Product SKU
            price_bucket: Price rounded to nearest dollar

        Returns:
            Redis key string
        """
        # Round price to nearest dollar
        price_rounded = round(price_bucket)
        key_data = f"{store}:{sku}:{price_rounded}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"alert:{key_hash}"

    def _get_cooldown_key(self, store: str, sku: str) -> str:
        """Generate cooldown key for a product."""
        key_data = f"{store}:{sku}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"cooldown:{key_hash}"

    async def is_duplicate(
        self, store: str, sku: str, current_price: Decimal
    ) -> bool:
        """
        Check if this alert is a duplicate.

        Args:
            store: Store name
            sku: Product SKU
            current_price: Current price

        Returns:
            True if duplicate, False otherwise
        """
        redis_client = await self._get_redis()
        dedupe_key = self._get_dedupe_key(store, sku, current_price)

        exists = await redis_client.exists(dedupe_key)
        return exists > 0

    async def mark_sent(
        self, store: str, sku: str, current_price: Decimal
    ) -> None:
        """
        Mark an alert as sent.

        Args:
            store: Store name
            sku: Product SKU
            current_price: Current price
        """
        redis_client = await self._get_redis()
        dedupe_key = self._get_dedupe_key(store, sku, current_price)

        # Set dedupe key with TTL
        ttl_seconds = self.dedupe_ttl_hours * 3600
        await redis_client.setex(dedupe_key, ttl_seconds, "1")

        logger.debug(
            f"Marked alert as sent: {dedupe_key} "
            f"(TTL: {self.dedupe_ttl_hours}h)"
        )

    async def is_in_cooldown(self, store: str, sku: str) -> bool:
        """
        Check if product is in cooldown period.

        Args:
            store: Store name
            sku: Product SKU

        Returns:
            True if in cooldown, False otherwise
        """
        redis_client = await self._get_redis()
        cooldown_key = self._get_cooldown_key(store, sku)

        exists = await redis_client.exists(cooldown_key)
        return exists > 0

    async def get_cooldown_remaining(self, store: str, sku: str) -> int:
        """
        Get remaining cooldown time in seconds.

        Args:
            store: Store name
            sku: Product SKU

        Returns:
            Remaining seconds, or 0 if not in cooldown
        """
        redis_client = await self._get_redis()
        cooldown_key = self._get_cooldown_key(store, sku)

        ttl = await redis_client.ttl(cooldown_key)
        return max(0, ttl)

    async def start_cooldown(self, store: str, sku: str) -> None:
        """
        Start cooldown period for a product.

        Args:
            store: Store name
            sku: Product SKU
        """
        redis_client = await self._get_redis()
        cooldown_key = self._get_cooldown_key(store, sku)

        cooldown_seconds = self.cooldown_minutes * 60
        await redis_client.setex(cooldown_key, cooldown_seconds, "1")

        logger.debug(
            f"Started cooldown for {store}:{sku} "
            f"({self.cooldown_minutes} minutes)"
        )

    async def can_bypass_cooldown(
        self, store: str, sku: str, current_price: Decimal, last_alert_price: Decimal
    ) -> bool:
        """
        Check if we can bypass cooldown because price dropped further.

        Args:
            store: Store name
            sku: Product SKU
            current_price: Current price
            last_alert_price: Price from last alert

        Returns:
            True if can bypass cooldown (price dropped further), False otherwise
        """
        if current_price < last_alert_price:
            logger.info(
                f"Bypassing cooldown for {store}:{sku}: "
                f"price dropped from ${last_alert_price} to ${current_price}"
            )
            return True
        return False

    async def get_last_alert_price(self, store: str, sku: str) -> Decimal | None:
        """
        Get the price from the last alert (for bypass check).

        Args:
            store: Store name
            sku: Product SKU

        Returns:
            Last alert price, or None if not found
        """
        redis_client = await self._get_redis()
        cooldown_key = self._get_cooldown_key(store, sku)

        # Store last price in cooldown key's value (simple approach)
        # For production, consider a separate key
        last_price_str = await redis_client.get(cooldown_key)
        if last_price_str and last_price_str != "1":
            try:
                return Decimal(last_price_str)
            except Exception:
                pass
        return None

    async def set_last_alert_price(
        self, store: str, sku: str, price: Decimal
    ) -> None:
        """
        Store the price from the last alert.

        Args:
            store: Store name
            sku: Product SKU
            price: Alert price
        """
        redis_client = await self._get_redis()
        cooldown_key = self._get_cooldown_key(store, sku)

        cooldown_seconds = self.cooldown_minutes * 60
        await redis_client.setex(cooldown_key, cooldown_seconds, str(price))
