"""Rate limiting for price fetchers using token bucket algorithm with jitter."""

import asyncio
import random
import time
from collections import defaultdict
from typing import Optional

from src.config import settings


class RateLimiter:
    """Token bucket rate limiter per domain with jitter and minimum intervals."""

    def __init__(self):
        self.buckets: dict[str, dict] = defaultdict(self._create_bucket)
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_request: dict[str, float] = {}
        self.domain_cooldowns: dict[str, float] = {}  # Domain -> cooldown until timestamp

    @staticmethod
    def _create_bucket() -> dict:
        """Create a new token bucket."""
        return {
            "tokens": 0.0,
            "last_refill": time.monotonic(),
            "last_request_time": 0.0,
        }

    async def acquire_with_interval(
        self,
        domain: str,
        min_interval: float,
        max_interval: float,
        jitter: float = 0.0,
    ) -> None:
        """
        Acquire with minimum interval and jitter (for retailer-specific rate limiting).

        Args:
            domain: Domain to rate limit
            min_interval: Minimum seconds between requests
            max_interval: Maximum seconds between requests
            jitter: Random jitter range in seconds (+/-)
        """
        async with self.locks[domain]:
            now = time.monotonic()
            last_time = self.last_request.get(domain, 0.0)
            elapsed = now - last_time

            # Check domain cooldown
            cooldown_until = self.domain_cooldowns.get(domain, 0.0)
            if now < cooldown_until:
                wait_time = cooldown_until - now
                await asyncio.sleep(wait_time)
                now = time.monotonic()

            # Calculate wait time with jitter
            interval = random.uniform(min_interval, max_interval)
            if jitter > 0:
                jitter_amount = random.uniform(-jitter, jitter)
                interval = max(min_interval, interval + jitter_amount)

            wait_needed = max(0.0, interval - elapsed)
            if wait_needed > 0:
                await asyncio.sleep(wait_needed)

            self.last_request[domain] = time.monotonic()

    async def acquire(
        self,
        domain: str,
        requests_per_second: float = None,
        burst_size: int = None,
    ) -> None:
        """
        Acquire a token for the given domain (legacy token bucket method).

        Args:
            domain: Domain to rate limit
            requests_per_second: Tokens per second (defaults to config)
            burst_size: Maximum burst size (defaults to requests_per_second)
        """
        if requests_per_second is None:
            requests_per_second = settings.requests_per_second
        if burst_size is None:
            burst_size = max(int(requests_per_second), 1)

        async with self.locks[domain]:
            bucket = self.buckets[domain]
            now = time.monotonic()
            elapsed = now - bucket["last_refill"]

            # Refill tokens based on elapsed time
            tokens_to_add = elapsed * requests_per_second
            bucket["tokens"] = min(
                bucket["tokens"] + tokens_to_add, burst_size
            )
            bucket["last_refill"] = now

            # Wait if no tokens available
            if bucket["tokens"] < 1.0:
                wait_time = (1.0 - bucket["tokens"]) / requests_per_second
                await asyncio.sleep(wait_time)
                bucket["tokens"] = 0.0
            else:
                bucket["tokens"] -= 1.0

            self.last_request[domain] = now

    def set_cooldown(self, domain: str, seconds: float) -> None:
        """
        Set domain cooldown (block requests for this domain until timestamp).

        Args:
            domain: Domain name
            seconds: Cooldown duration in seconds
        """
        self.domain_cooldowns[domain] = time.monotonic() + seconds

    async def wait_for_backoff(
        self,
        domain: str,
        attempt: int,
        multiplier: float = 2.0,
        max_seconds: float = 60.0,
    ) -> None:
        """
        Wait with exponential backoff after a failed request.

        Args:
            domain: Domain name
            attempt: Attempt number (1-based)
            multiplier: Backoff multiplier
            max_seconds: Maximum backoff time in seconds
        """
        wait_time = min(multiplier ** (attempt - 1), max_seconds)
        await asyncio.sleep(wait_time)


# Global rate limiter instance
rate_limiter = RateLimiter()
