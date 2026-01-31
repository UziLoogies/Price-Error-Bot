"""Centralized HTTP client with per-site policies and status-aware error handling."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Retryable exceptions (transport errors)
RETRYABLE_EXC = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


@dataclass(frozen=True)
class SitePolicy:
    """Per-site HTTP request policy configuration."""
    
    name: str
    max_attempts: int = 3
    timeout: httpx.Timeout = None  # Will be set to default if None
    max_concurrency_per_host: int = 2
    requires_js: bool = False
    treat_403_as_blocked: bool = True
    treat_404_as_permanent: bool = True
    treat_401_as_blocked: bool = True
    
    def __post_init__(self):
        """Set default timeout if not provided."""
        if self.timeout is None:
            object.__setattr__(
                self,
                'timeout',
                httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
            )


class BlockedError(RuntimeError):
    """Raised when access is blocked (403, 401, or /blocked redirect)."""
    pass


class PermanentURLError(RuntimeError):
    """Raised when URL is permanently invalid (404)."""
    pass


class TransientFetchError(RuntimeError):
    """Raised when fetch fails after retries (5xx, timeouts, etc.)."""
    pass


class RateLimitedError(RuntimeError):
    """Raised when rate limited (429)."""
    
    def __init__(self, retry_after: Optional[int] = None):
        super().__init__("Rate limited")
        self.retry_after = retry_after


def default_headers() -> dict[str, str]:
    """Get default browser-like headers."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html, application/xhtml+xml, application/xml; q=0.9, */*; q=0.8",
        "Accept-Language": "en-US, en; q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


async def fetch_with_policy(
    client: httpx.AsyncClient,
    url: str,
    policy: SitePolicy,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Response:
    """
    Fetch URL with per-site policy and status-aware error handling.
    
    Args:
        client: httpx AsyncClient instance
        url: URL to fetch
        policy: SitePolicy configuration
        headers: Optional additional headers (merged with defaults)
        
    Returns:
        httpx.Response on success
        
    Raises:
        BlockedError: If access is blocked (403, 401, or /blocked redirect)
        PermanentURLError: If URL is permanently invalid (404)
        RateLimitedError: If rate limited (429)
        TransientFetchError: If fetch fails after retries
    """
    hdrs = default_headers()
    if headers:
        hdrs.update(headers)
    
    last_exc: Exception | None = None
    
    for attempt in range(1, policy.max_attempts + 1):
        try:
            resp = await client.get(
                url,
                headers=hdrs,
                timeout=policy.timeout,
                follow_redirects=True
            )
            
            # Check for /blocked redirect (Walmart and others)
            if "/blocked" in str(resp.url).lower():
                raise BlockedError(f"{policy.name}: blocked redirect: {resp.url}")
            
            sc = resp.status_code
            
            # Handle 404 as permanent failure
            if sc == 404 and policy.treat_404_as_permanent:
                raise PermanentURLError(f"{policy.name}: 404 for {url}")
            
            # Handle 401/403 as blocked
            if sc in (401, 403):
                if (sc == 401 and policy.treat_401_as_blocked) or \
                   (sc == 403 and policy.treat_403_as_blocked):
                    raise BlockedError(f"{policy.name}: {sc} for {url}")
            
            # Handle 429 rate limiting
            if sc == 429:
                retry_after = resp.headers.get("Retry-After")
                retry_seconds = None
                if retry_after:
                    try:
                        retry_seconds = int(retry_after)
                    except (ValueError, TypeError):
                        pass
                raise RateLimitedError(retry_after=retry_seconds)
            
            # Success (200-299, 300-399 handled by follow_redirects)
            if 200 <= sc < 300:
                return resp
            
            # Handle 5xx server errors (transient, will retry)
            if 500 <= sc < 600:
                if attempt < policy.max_attempts:
                    # Will retry below
                    last_exc = TransientFetchError(f"{policy.name}: {sc} for {url}")
                    sleep_s = (2 ** attempt) + random.random()
                    logger.warning(
                        f"{policy.name}: Server error {sc}, retrying in {sleep_s:.1f}s "
                        f"(attempt {attempt}/{policy.max_attempts})"
                    )
                    await asyncio.sleep(sleep_s)
                    continue
                else:
                    # Final attempt failed
                    raise TransientFetchError(f"{policy.name}: {sc} for {url} after {policy.max_attempts} attempts")
            
            # Other status codes - treat as transient for retry
            if attempt < policy.max_attempts:
                last_exc = TransientFetchError(f"{policy.name}: unexpected status {sc} for {url}")
                sleep_s = (2 ** attempt) + random.random()
                logger.warning(
                    f"{policy.name}: Unexpected status {sc}, retrying in {sleep_s:.1f}s "
                    f"(attempt {attempt}/{policy.max_attempts})"
                )
                await asyncio.sleep(sleep_s)
                continue
            else:
                raise TransientFetchError(f"{policy.name}: status {sc} for {url} after {policy.max_attempts} attempts")
            
        except RateLimitedError as e:
            # Calculate backoff: use Retry-After if available, otherwise exponential
            if e.retry_after is not None:
                sleep_s = float(e.retry_after)
            else:
                sleep_s = (2 ** attempt) + random.random()
            
            if attempt < policy.max_attempts:
                logger.warning(
                    f"{policy.name}: Rate limited (429), retrying in {sleep_s:.1f}s "
                    f"(attempt {attempt}/{policy.max_attempts})"
                )
                await asyncio.sleep(sleep_s)
                last_exc = e
                continue
            else:
                raise
        
        except RETRYABLE_EXC as e:
            # Transport errors: retry with exponential backoff
            sleep_s = (2 ** attempt) + random.random()
            if attempt < policy.max_attempts:
                logger.warning(
                    f"{policy.name}: Transport error ({type(e).__name__}), "
                    f"retrying in {sleep_s:.1f}s (attempt {attempt}/{policy.max_attempts})"
                )
                await asyncio.sleep(sleep_s)
                last_exc = e
                continue
            else:
                raise TransientFetchError(
                    f"{policy.name}: Transport error after {policy.max_attempts} attempts: {url}"
                ) from e
        
        except (BlockedError, PermanentURLError):
            # Don't retry these - re-raise immediately
            raise
        
        except TransientFetchError as e:
            # Retry transient errors
            if attempt < policy.max_attempts:
                sleep_s = (2 ** attempt) + random.random()
                logger.warning(
                    f"{policy.name}: Transient error, retrying in {sleep_s:.1f}s "
                    f"(attempt {attempt}/{policy.max_attempts})"
                )
                await asyncio.sleep(sleep_s)
                last_exc = e
                continue
            else:
                # Final attempt failed
                raise
    
    # If we get here, all retries exhausted
    raise TransientFetchError(
        f"{policy.name}: failed after {policy.max_attempts} attempts: {url}"
    ) from last_exc


# Per-site policy definitions
POLICIES: dict[str, SitePolicy] = {
    "microcenter": SitePolicy(
        name="microcenter",
        max_attempts=2,
        timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0),
    ),
    "newegg": SitePolicy(
        name="newegg",
        max_attempts=2,
        timeout=httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0),
    ),
    "bestbuy": SitePolicy(
        name="bestbuy",
        max_attempts=4,
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
        max_concurrency_per_host=1,  # Reduced to prevent disconnects
    ),
    "costco": SitePolicy(
        name="costco",
        max_attempts=1,  # Blocked site, don't waste retries
        treat_403_as_blocked=True,
        treat_401_as_blocked=True,
    ),
    "macys": SitePolicy(
        name="macys",
        max_attempts=1,  # Blocked site, don't waste retries
        treat_403_as_blocked=True,
        treat_401_as_blocked=True,
    ),
    "lowes": SitePolicy(
        name="lowes",
        max_attempts=1,  # Blocked site, don't waste retries
        treat_403_as_blocked=True,
        treat_401_as_blocked=True,
    ),
    "walmart": SitePolicy(
        name="walmart",
        max_attempts=1,  # Often blocked, check for /blocked redirect
        treat_403_as_blocked=True,
        treat_401_as_blocked=True,
    ),
    # Default policy for unknown sites
    "default": SitePolicy(
        name="default",
        max_attempts=3,
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
    ),
}


def get_policy_for_store(store: str) -> SitePolicy:
    """
    Get site policy for a store identifier.
    
    Args:
        store: Store identifier (e.g., "bestbuy", "walmart")
        
    Returns:
        SitePolicy for the store, or default policy if not found
    """
    store_lower = store.lower()
    
    # Direct match
    if store_lower in POLICIES:
        return POLICIES[store_lower]
    
    # Try partial matches
    for key, policy in POLICIES.items():
        if key != "default" and key in store_lower:
            return policy
    
    # Return default
    return POLICIES["default"]
