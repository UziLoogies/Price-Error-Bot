"""HTTP caching with ETag and Last-Modified support.

Implements conditional HTTP requests to avoid re-downloading unchanged pages.
Uses Redis to store cached content and cache headers.
"""

import hashlib
import logging
from typing import Optional, Dict, Any

import redis.asyncio as redis

from src.config import settings
from src import metrics

logger = logging.getLogger(__name__)


class HTTPCache:
    """
    HTTP cache using Redis for ETag-based conditional requests.
    
    Stores:
    - Cached HTML content
    - ETag header value
    - Last-Modified header value
    - Cache timestamp
    """
    
    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: Optional[int] = None):
        self.redis_url = redis_url or settings.redis_url
        self.ttl = ttl_seconds or settings.http_cache_ttl_seconds
        self._redis: Optional[redis.Redis] = None
    
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
    
    def _get_cache_key(self, url: str) -> str:
        """Generate cache key from URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return f"http_cache:{url_hash}"
    
    async def get_conditional_headers(self, url: str) -> Dict[str, str]:
        """
        Get conditional request headers if cached content exists.
        
        Args:
            url: URL to check cache for
            
        Returns:
            Dict with If-None-Match and/or If-Modified-Since headers
        """
        if not settings.http_cache_enabled:
            return {}
        
        try:
            redis_client = await self._get_redis()
            cache_key = self._get_cache_key(url)
            
            cached = await redis_client.hgetall(cache_key)
            if not cached:
                return {}
            
            headers = {}
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
            
            return headers
            
        except Exception as e:
            logger.debug(f"Error getting cache headers for {url}: {e}")
            return {}
    
    async def get_cached_content(self, url: str) -> Optional[str]:
        """
        Get cached HTML content for a URL.
        
        Args:
            url: URL to get cached content for
            
        Returns:
            Cached HTML content or None
        """
        if not settings.http_cache_enabled:
            return None
        
        try:
            redis_client = await self._get_redis()
            cache_key = self._get_cache_key(url)
            
            content = await redis_client.hget(cache_key, "content")
            return content
            
        except Exception as e:
            logger.debug(f"Error getting cached content for {url}: {e}")
            return None
    
    async def is_not_modified(self, url: str, response: Any) -> bool:
        """
        Check if response indicates content is not modified (304).
        
        Args:
            url: Request URL
            response: HTTP response object (httpx.Response)
            
        Returns:
            True if 304 Not Modified, False otherwise
        """
        return response.status_code == 304
    
    async def store(
        self,
        url: str,
        content: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        store: Optional[str] = None,
    ) -> None:
        """
        Store content with cache headers.
        
        Args:
            url: URL of the content
            content: HTML content to cache
            etag: ETag header value
            last_modified: Last-Modified header value
            store: Store name for metrics
        """
        if not settings.http_cache_enabled:
            return
        
        try:
            redis_client = await self._get_redis()
            cache_key = self._get_cache_key(url)
            
            cache_data = {
                "content": content,
                "etag": etag or "",
                "last_modified": last_modified or "",
            }
            
            await redis_client.hset(cache_key, mapping=cache_data)
            await redis_client.expire(cache_key, self.ttl)
            
            logger.debug(
                f"Cached content for {url} "
                f"(ETag: {etag[:20] if etag else 'none'}..., TTL: {self.ttl}s)"
            )
            
        except Exception as e:
            logger.debug(f"Error caching content for {url}: {e}")
    
    async def invalidate(self, url: str) -> None:
        """
        Invalidate cached content for a URL.
        
        Args:
            url: URL to invalidate
        """
        try:
            redis_client = await self._get_redis()
            cache_key = self._get_cache_key(url)
            await redis_client.delete(cache_key)
            logger.debug(f"Invalidated cache for {url}")
            
        except Exception as e:
            logger.debug(f"Error invalidating cache for {url}: {e}")
    
    async def handle_response(
        self,
        url: str,
        response: Any,
        store: Optional[str] = None,
    ) -> tuple[str, bool]:
        """
        Handle HTTP response and return content with cache status.
        
        For 304 responses, returns cached content.
        For 200 responses, caches new content.
        
        Args:
            url: Request URL
            response: HTTP response object (httpx.Response)
            store: Store name for metrics
            
        Returns:
            Tuple of (content, is_from_cache)
        """
        if response.status_code == 304:
            # Content not modified, use cached version
            cached_content = await self.get_cached_content(url)
            if cached_content:
                if store:
                    metrics.record_cache_hit(store)
                logger.debug(f"Cache hit (304) for {url}")
                return cached_content, True
            else:
                # Cache miss despite 304 - shouldn't happen but handle gracefully
                logger.warning(f"304 response but no cached content for {url}")
                if store:
                    metrics.record_cache_miss(store)
                return "", False
        
        # New content, cache it
        content = response.text
        
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        
        if etag or last_modified:
            await self.store(url, content, etag, last_modified, store)
        
        if store:
            metrics.record_cache_miss(store)
        
        return content, False
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dict with cache statistics
        """
        try:
            redis_client = await self._get_redis()
            
            # Count cache entries using SCAN (non-blocking) instead of KEYS
            count = 0
            cursor = 0
            pattern = "http_cache:*"
            
            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
                count += len(keys)
                if cursor == 0:
                    break
            
            return {
                "cached_urls": count,
                "ttl_seconds": self.ttl,
                "enabled": settings.http_cache_enabled,
            }
            
        except Exception as e:
            logger.debug(f"Error getting cache stats: {e}")
            return {
                "error": str(e),
                "enabled": settings.http_cache_enabled,
            }


# Global instance
http_cache = HTTPCache()
