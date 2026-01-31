"""Store health tracking for adaptive rate limiting.

Tracks request success/failure rates, response times, and blocks to
dynamically adjust rate limiting parameters per store.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from collections import deque

from src.config import settings
from src import metrics

logger = logging.getLogger(__name__)


@dataclass
class RequestResult:
    """Result of a single request."""
    timestamp: datetime
    success: bool
    duration_ms: float
    status_code: Optional[int] = None
    blocked: bool = False
    block_type: Optional[str] = None


@dataclass
class StoreHealthMetrics:
    """Health metrics for a single store."""
    store: str
    avg_response_time_ms: float = 0.0
    error_rate: float = 0.0  # 0.0 - 1.0
    last_429_at: Optional[datetime] = None
    last_block_at: Optional[datetime] = None
    consecutive_failures: int = 0
    total_requests: int = 0
    successful_requests: int = 0
    
    # Rolling window of recent requests (last 100)
    recent_requests: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def update_from_recent(self):
        """Update computed metrics from recent requests."""
        if not self.recent_requests:
            return
        
        # Calculate error rate from recent requests
        successes = sum(1 for r in self.recent_requests if r.success)
        self.error_rate = 1.0 - (successes / len(self.recent_requests))
        
        # Calculate average response time
        durations = [r.duration_ms for r in self.recent_requests if r.success]
        if durations:
            self.avg_response_time_ms = sum(durations) / len(durations)


class StoreHealthTracker:
    """
    Tracks health metrics per store for adaptive rate limiting.
    
    Provides:
    - Request success/failure tracking
    - Response time monitoring
    - Block detection tracking
    - Recommended delay calculations
    """
    
    def __init__(self):
        self._metrics: Dict[str, StoreHealthMetrics] = {}
    
    def _get_or_create_metrics(self, store: str) -> StoreHealthMetrics:
        """Get or create metrics for a store."""
        if store not in self._metrics:
            self._metrics[store] = StoreHealthMetrics(store=store)
        return self._metrics[store]
    
    async def record_request(
        self,
        store: str,
        success: bool,
        duration_ms: float,
        status_code: Optional[int] = None,
        blocked: bool = False,
        block_type: Optional[str] = None,
    ) -> None:
        """
        Record a request outcome for health tracking.
        
        Args:
            store: Store identifier
            success: Whether the request was successful
            duration_ms: Request duration in milliseconds
            status_code: HTTP status code
            blocked: Whether the request was blocked
            block_type: Type of block (captcha, cloudflare, etc.)
        """
        store_metrics = self._get_or_create_metrics(store)
        now = datetime.utcnow()
        
        # Create request result
        result = RequestResult(
            timestamp=now,
            success=success,
            duration_ms=duration_ms,
            status_code=status_code,
            blocked=blocked,
            block_type=block_type,
        )
        
        # Add to recent requests
        store_metrics.recent_requests.append(result)
        
        # Update totals
        store_metrics.total_requests += 1
        if success:
            store_metrics.successful_requests += 1
            store_metrics.consecutive_failures = 0
        else:
            store_metrics.consecutive_failures += 1
        
        # Track special status codes
        if status_code == 429:
            store_metrics.last_429_at = now
            logger.warning(f"Store {store} received 429 rate limit response")
        
        # Track blocks
        if blocked:
            store_metrics.last_block_at = now
            if block_type:
                metrics.record_scan_block(store, block_type)
        
        # Update computed metrics
        store_metrics.update_from_recent()
        
        # Record prometheus metrics
        metrics.record_store_response(store, duration_ms, success)
        metrics.update_store_health(
            store,
            error_rate=store_metrics.error_rate,
            consecutive_failures=store_metrics.consecutive_failures,
            delay=self.get_recommended_delay(store),
        )
        
        logger.debug(
            f"Recorded request for {store}: success={success}, "
            f"duration={duration_ms:.0f}ms, error_rate={store_metrics.error_rate:.2%}"
        )
    
    def get_recommended_delay(self, store: str) -> float:
        """
        Calculate recommended delay based on health metrics.
        
        Returns a delay in seconds that adapts to the store's health:
        - Higher delay when error rate is high
        - Higher delay after 429 responses
        - Higher delay when response times are slow
        
        Args:
            store: Store identifier
            
        Returns:
            Recommended delay in seconds
        """
        if not settings.adaptive_rate_limiting_enabled:
            return settings.adaptive_base_delay
        
        store_metrics = self._metrics.get(store)
        if not store_metrics:
            return settings.adaptive_base_delay
        
        base_delay = settings.adaptive_base_delay
        now = datetime.utcnow()
        
        # Increase on high error rate
        if store_metrics.error_rate > settings.adaptive_error_rate_threshold:
            multiplier = 1 + (store_metrics.error_rate * 2)  # Up to 3x at 100% error rate
            base_delay *= multiplier
            logger.debug(f"Store {store}: high error rate ({store_metrics.error_rate:.2%}), delay *= {multiplier:.2f}")
        
        # Back off after 429s (within cooldown window)
        if store_metrics.last_429_at:
            time_since_429 = (now - store_metrics.last_429_at).total_seconds()
            if time_since_429 < settings.adaptive_429_cooldown_seconds:
                # More aggressive backoff closer to the 429
                backoff_factor = 3.0 * (1.0 - time_since_429 / settings.adaptive_429_cooldown_seconds)
                base_delay *= (1 + backoff_factor)
                logger.debug(f"Store {store}: recent 429 ({time_since_429:.0f}s ago), delay *= {1 + backoff_factor:.2f}")
        
        # Back off after blocks
        if store_metrics.last_block_at:
            time_since_block = (now - store_metrics.last_block_at).total_seconds()
            if time_since_block < settings.adaptive_429_cooldown_seconds:
                backoff_factor = 2.0 * (1.0 - time_since_block / settings.adaptive_429_cooldown_seconds)
                base_delay *= (1 + backoff_factor)
                logger.debug(f"Store {store}: recent block ({time_since_block:.0f}s ago), delay *= {1 + backoff_factor:.2f}")
        
        # Slow down on high latency
        if store_metrics.avg_response_time_ms > settings.adaptive_high_latency_ms:
            latency_factor = 1.5
            base_delay *= latency_factor
            logger.debug(f"Store {store}: high latency ({store_metrics.avg_response_time_ms:.0f}ms), delay *= {latency_factor:.2f}")
        
        # Back off on consecutive failures
        if store_metrics.consecutive_failures > 0:
            failure_factor = min(1 + (store_metrics.consecutive_failures * 0.5), 5.0)
            base_delay *= failure_factor
            logger.debug(f"Store {store}: consecutive failures ({store_metrics.consecutive_failures}), delay *= {failure_factor:.2f}")
        
        # Cap at maximum delay
        final_delay = min(base_delay, settings.adaptive_max_delay)
        
        return final_delay
    
    def get_health_summary(self, store: str) -> Dict[str, Any]:
        """
        Get health summary for a store.
        
        Args:
            store: Store identifier
            
        Returns:
            Dict with health summary
        """
        store_metrics = self._metrics.get(store)
        if not store_metrics:
            return {
                "store": store,
                "status": "unknown",
                "no_data": True,
            }
        
        # Determine health status
        if store_metrics.error_rate > 0.5:
            status = "critical"
        elif store_metrics.error_rate > 0.2:
            status = "degraded"
        elif store_metrics.consecutive_failures > 3:
            status = "warning"
        else:
            status = "healthy"
        
        return {
            "store": store,
            "status": status,
            "total_requests": store_metrics.total_requests,
            "successful_requests": store_metrics.successful_requests,
            "error_rate": round(store_metrics.error_rate, 4),
            "avg_response_time_ms": round(store_metrics.avg_response_time_ms, 2),
            "consecutive_failures": store_metrics.consecutive_failures,
            "last_429_at": store_metrics.last_429_at.isoformat() if store_metrics.last_429_at else None,
            "last_block_at": store_metrics.last_block_at.isoformat() if store_metrics.last_block_at else None,
            "recommended_delay_seconds": round(self.get_recommended_delay(store), 2),
        }
    
    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Get health summary for all tracked stores.
        
        Returns:
            Dict mapping store names to health summaries
        """
        return {
            store: self.get_health_summary(store)
            for store in self._metrics.keys()
        }
    
    def reset_store(self, store: str) -> None:
        """
        Reset health metrics for a store.
        
        Args:
            store: Store identifier
        """
        if store in self._metrics:
            del self._metrics[store]
            logger.info(f"Reset health metrics for {store}")
    
    def is_store_healthy(self, store: str) -> bool:
        """
        Check if a store is considered healthy enough for scanning.
        
        Args:
            store: Store identifier
            
        Returns:
            True if store is healthy, False otherwise
        """
        store_metrics = self._metrics.get(store)
        if not store_metrics:
            return True  # Unknown = assume healthy
        
        # Unhealthy if too many consecutive failures
        if store_metrics.consecutive_failures >= 10:
            return False
        
        # Unhealthy if error rate is very high
        if store_metrics.error_rate > 0.8:
            return False
        
        return True


# Global instance
store_health = StoreHealthTracker()
