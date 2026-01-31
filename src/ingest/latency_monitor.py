"""Latency monitoring and optimization system.

Tracks per-domain latency, calculates percentiles, detects slow proxies,
and optimizes based on region.
"""

import asyncio
import logging
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LatencyStats:
    """Latency statistics for a domain."""
    domain: str
    p50: float  # Median latency (ms)
    p95: float  # 95th percentile (ms)
    p99: float  # 99th percentile (ms)
    avg: float  # Average latency (ms)
    min_latency: float
    max_latency: float
    sample_count: int
    last_updated: datetime


class LatencyMonitor:
    """
    Monitors and tracks latency for optimization.
    
    Features:
    - Per-domain latency tracking
    - Latency percentile calculation (p50, p95, p99)
    - Automatic slow proxy detection
    - Region-based latency optimization
    """
    
    def __init__(self, redis_url: Optional[str] = None, window_size: int = 100):
        """
        Initialize latency monitor.
        
        Args:
            redis_url: Redis URL for persistence
            window_size: Number of samples to keep per domain
        """
        self.redis_url = redis_url or settings.redis_url
        self.window_size = window_size
        self._redis: Optional[redis.Redis] = None
        
        # In-memory latency samples (domain -> deque of latencies)
        self._samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._samples_lock = asyncio.Lock()
    
    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def record_latency(
        self,
        domain: str,
        latency_ms: float,
        proxy_id: Optional[int] = None,
        region: Optional[str] = None,
    ) -> None:
        """
        Record latency for a domain.
        
        Args:
            domain: Target domain
            latency_ms: Latency in milliseconds
            proxy_id: Optional proxy ID
            region: Optional geo region
        """
        async with self._samples_lock:
            self._samples[domain].append(latency_ms)
        
        # Also store in Redis for persistence
        try:
            redis_client = await self._get_redis()
            key = f"latency:{domain}"
            
            # Store in sorted set (score = timestamp, value = latency)
            timestamp = time.time()
            await redis_client.zadd(key, {str(latency_ms): timestamp})
            
            # Keep only last window_size samples
            await redis_client.zremrangebyrank(key, 0, -(self.window_size + 1))
            
            # Store proxy-specific latency if provided
            if proxy_id:
                proxy_key = f"latency:proxy:{proxy_id}"
                await redis_client.zadd(proxy_key, {str(latency_ms): timestamp})
                await redis_client.zremrangebyrank(proxy_key, 0, -(self.window_size + 1))
        
        except Exception as e:
            logger.debug(f"Error recording latency to Redis: {e}")
    
    async def get_latency_stats(self, domain: str) -> Optional[LatencyStats]:
        """
        Get latency statistics for a domain.
        
        Args:
            domain: Domain to get stats for
            
        Returns:
            LatencyStats or None if insufficient data
        """
        async with self._samples_lock:
            samples = list(self._samples[domain])
        
        # Also try to load from Redis
        try:
            redis_client = await self._get_redis()
            key = f"latency:{domain}"
            redis_samples = await redis_client.zrange(key, -self.window_size, -1)
            if redis_samples:
                # Convert to floats
                samples.extend([float(s) for s in redis_samples])
        except Exception:
            pass
        
        if len(samples) < 5:
            return None
        
        # Calculate percentiles
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        
        p50 = sorted_samples[n // 2]
        p95 = sorted_samples[int(n * 0.95)] if n > 20 else sorted_samples[-1]
        p99 = sorted_samples[int(n * 0.99)] if n > 50 else sorted_samples[-1]
        
        return LatencyStats(
            domain=domain,
            p50=p50,
            p95=p95,
            p99=p99,
            avg=statistics.mean(samples),
            min_latency=min(samples),
            max_latency=max(samples),
            sample_count=len(samples),
            last_updated=datetime.utcnow(),
        )
    
    async def is_slow_proxy(
        self,
        proxy_id: int,
        threshold_p95: float = 5000.0,
    ) -> bool:
        """
        Check if a proxy is slow based on latency.
        
        Args:
            proxy_id: Proxy ID
            threshold_p95: P95 latency threshold in ms
            
        Returns:
            True if proxy is slow
        """
        try:
            redis_client = await self._get_redis()
            key = f"latency:proxy:{proxy_id}"
            samples = await redis_client.zrange(key, -self.window_size, -1)
            
            if len(samples) < 10:
                return False  # Not enough data
            
            latencies = [float(s) for s in samples]
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            p95 = sorted_latencies[int(n * 0.95)]
            
            return p95 > threshold_p95
        
        except Exception as e:
            logger.debug(f"Error checking slow proxy: {e}")
            return False
    
    async def get_best_region(self, domain: str) -> Optional[str]:
        """
        Determine best region for a domain based on latency.
        
        Args:
            domain: Target domain
            
        Returns:
            Best region or None
        """
        # This would require region-specific latency tracking
        # For now, return None (no region preference)
        return None
    
    async def get_all_domain_stats(self) -> Dict[str, LatencyStats]:
        """Get latency stats for all monitored domains."""
        async with self._samples_lock:
            domains = list(self._samples.keys())
        
        stats = {}
        for domain in domains:
            domain_stats = await self.get_latency_stats(domain)
            if domain_stats:
                stats[domain] = domain_stats
        
        return stats
    
    async def get_slow_domains(self, threshold_p95: float = 2000.0) -> List[str]:
        """
        Get list of domains with high latency.
        
        Args:
            threshold_p95: P95 latency threshold in ms
            
        Returns:
            List of slow domain names
        """
        all_stats = await self.get_all_domain_stats()
        slow = [
            domain for domain, stats in all_stats.items()
            if stats.p95 > threshold_p95
        ]
        return slow


# Global latency monitor instance
latency_monitor = LatencyMonitor()
