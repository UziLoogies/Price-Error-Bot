"""Hybrid proxy manager for datacenter and residential proxies.

Implements intelligent routing between proxy types based on:
- Target site protection level
- Proxy health and success rates
- Cost considerations
- Automatic fallback strategies
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import ProxyConfig
from src.db.session import AsyncSessionLocal
from src.ingest.proxy_manager import ProxyInfo

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    """Statistics for a proxy."""
    proxy_id: int
    success_rate: float
    avg_latency_ms: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    last_used: Optional[datetime]
    last_success: Optional[datetime]
    cost_per_gb: Optional[float]
    proxy_type: str


@dataclass
class SiteProtection:
    """Protection level for a site."""
    domain: str
    protection_level: str  # 'low', 'medium', 'high'
    requires_residential: bool = False
    last_blocked_at: Optional[datetime] = None
    block_count: int = 0


class HybridProxyManager:
    """
    Manages hybrid proxy pool with intelligent routing.
    
    Features:
    - Separate pools for datacenter and residential proxies
    - Automatic routing based on site protection
    - Health scoring system
    - Intelligent fallback (datacenter → residential on block)
    - Geo-targeting support
    - Cost tracking for residential proxies
    """
    
    def __init__(self):
        """Initialize hybrid proxy manager."""
        self._datacenter_pool: List[ProxyInfo] = []
        self._residential_pool: List[ProxyInfo] = []
        self._isp_pool: List[ProxyInfo] = []
        
        # Site protection tracking
        self._site_protection: Dict[str, SiteProtection] = {}
        
        # Proxy stats cache
        self._proxy_stats: Dict[int, ProxyStats] = {}
        self._stats_lock = asyncio.Lock()
        
        # Cost tracking
        self._monthly_cost: float = 0.0
        self._cost_limit = getattr(settings, 'residential_proxy_cost_limit', 100.0)
        
        # Load proxies on init
        self._load_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        """Initialize and load proxies."""
        await self.load_proxies()
    
    async def load_proxies(self):
        """Load proxies from database and organize by type."""
        async with AsyncSessionLocal() as db:
            query = select(ProxyConfig).where(ProxyConfig.enabled == True)
            result = await db.execute(query)
            proxy_configs = result.scalars().all()
            
            self._datacenter_pool.clear()
            self._residential_pool.clear()
            self._isp_pool.clear()
            
            for config in proxy_configs:
                proxy_info = ProxyInfo(
                    id=config.id,
                    host=config.host,
                    port=config.port,
                    username=config.username,
                    password=config.password,
                    proxy_type=config.proxy_type or "datacenter",
                )
                
                # Add to appropriate pool
                if config.proxy_type == "residential":
                    self._residential_pool.append(proxy_info)
                elif config.proxy_type == "isp":
                    self._isp_pool.append(proxy_info)
                else:  # datacenter (default)
                    self._datacenter_pool.append(proxy_info)
                
                # Load stats
                self._proxy_stats[config.id] = ProxyStats(
                    proxy_id=config.id,
                    success_rate=config.success_rate,
                    avg_latency_ms=config.avg_latency_ms,
                    total_requests=0,  # Will be updated from DB
                    successful_requests=0,
                    failed_requests=0,
                    last_used=config.last_used,
                    last_success=config.last_success,
                    cost_per_gb=config.cost_per_gb,
                    proxy_type=config.proxy_type,
                )
            
            logger.info(
                f"Loaded proxies: {len(self._datacenter_pool)} datacenter, "
                f"{len(self._residential_pool)} residential, "
                f"{len(self._isp_pool)} ISP"
            )
    
    async def get_proxy_for_site(
        self,
        domain: str,
        use_residential: Optional[bool] = None,
        region: Optional[str] = None,
    ) -> Optional[ProxyInfo]:
        """
        Get best proxy for a site based on protection level and health.
        
        Args:
            domain: Target domain
            use_residential: Force residential (None = auto-detect)
            region: Preferred geo region
            
        Returns:
            ProxyInfo or None if no proxies available
        """
        # Get site protection level
        protection = self._get_site_protection(domain)
        
        # Determine proxy type needed
        if use_residential is None:
            use_residential = (
                protection.requires_residential or
                protection.protection_level == "high" or
                (protection.protection_level == "medium" and protection.block_count > 3)
            )
        
        # Select pool
        if use_residential:
            pool = self._residential_pool
            if not pool and self._isp_pool:
                pool = self._isp_pool  # Fallback to ISP if no residential
        else:
            # Prefer ISP over datacenter if available
            pool = self._isp_pool if self._isp_pool else self._datacenter_pool
        
        if not pool:
            logger.warning(f"No proxies available for {domain} (type: {'residential' if use_residential else 'datacenter'})")
            return None
        
        # Select best proxy from pool using health scoring
        best_proxy = await self._select_best_proxy(pool, domain, region)
        
        return best_proxy
    
    def _get_site_protection(self, domain: str) -> SiteProtection:
        """Get or create site protection info."""
        if domain not in self._site_protection:
            # Default protection levels for known sites
            protection_map = {
                "amazon.com": "high",
                "www.amazon.com": "high",
                "walmart.com": "medium",
                "www.walmart.com": "medium",
                "target.com": "medium",
                "www.target.com": "medium",
                "bestbuy.com": "low",
                "www.bestbuy.com": "low",
            }
            
            protection_level = protection_map.get(domain, "medium")
            self._site_protection[domain] = SiteProtection(
                domain=domain,
                protection_level=protection_level,
                requires_residential=(protection_level == "high"),
            )
        
        return self._site_protection[domain]
    
    async def _select_best_proxy(
        self,
        pool: List[ProxyInfo],
        domain: str,
        region: Optional[str] = None,
    ) -> Optional[ProxyInfo]:
        """Select best proxy from pool based on health score."""
        if not pool:
            return None
        
        scored_proxies = []
        
        for proxy in pool:
            stats = self._proxy_stats.get(proxy.id)
            if not stats:
                # Default stats for new proxies
                stats = ProxyStats(
                    proxy_id=proxy.id,
                    success_rate=1.0,
                    avg_latency_ms=0.0,
                    total_requests=0,
                    successful_requests=0,
                    failed_requests=0,
                    last_used=None,
                    last_success=None,
                    cost_per_gb=None,
                    proxy_type="datacenter",
                )
            
            # Calculate health score
            score = self._calculate_health_score(stats, domain, region)
            scored_proxies.append((score, proxy))
        
        # Sort by score (highest first)
        scored_proxies.sort(key=lambda x: x[0], reverse=True)
        
        return scored_proxies[0][1] if scored_proxies else None
    
    def _calculate_health_score(
        self,
        stats: ProxyStats,
        domain: str,
        region: Optional[str] = None,
    ) -> float:
        """Calculate health score for proxy selection."""
        score = 0.0
        
        # Success rate (0-50 points)
        score += stats.success_rate * 50
        
        # Latency (0-30 points, lower is better)
        if stats.avg_latency_ms > 0:
            latency_score = max(0, 30 - (stats.avg_latency_ms / 100))
            score += latency_score
        else:
            score += 15  # Unknown latency, give medium score
        
        # Recent success (0-10 points)
        if stats.last_success:
            hours_since_success = (datetime.utcnow() - stats.last_success).total_seconds() / 3600
            if hours_since_success < 1:
                score += 10
            elif hours_since_success < 24:
                score += 5
        
        # Cost penalty for residential (0-10 points deduction)
        if stats.proxy_type == "residential" and stats.cost_per_gb:
            # Penalize expensive proxies
            if stats.cost_per_gb > 10:
                score -= 10
            elif stats.cost_per_gb > 5:
                score -= 5
        
        return max(0.0, score)
    
    async def mark_proxy_result(
        self,
        proxy_id: int,
        success: bool,
        latency_ms: float,
        data_transferred_mb: float = 0.0,
    ) -> None:
        """
        Record proxy usage result and update statistics.
        
        Args:
            proxy_id: Proxy ID
            success: Whether request succeeded
            latency_ms: Request latency in milliseconds
            data_transferred_mb: Data transferred in MB (for cost calculation)
        """
        async with self._stats_lock:
            if proxy_id not in self._proxy_stats:
                return
            
            stats = self._proxy_stats[proxy_id]
            stats.total_requests += 1
            
            if success:
                stats.successful_requests += 1
                stats.last_success = datetime.utcnow()
                # Update average latency
                if stats.avg_latency_ms == 0:
                    stats.avg_latency_ms = latency_ms
                else:
                    stats.avg_latency_ms = (stats.avg_latency_ms * 0.9 + latency_ms * 0.1)
            else:
                stats.failed_requests += 1
            
            # Update success rate
            stats.success_rate = stats.successful_requests / stats.total_requests if stats.total_requests > 0 else 1.0
            stats.last_used = datetime.utcnow()
            
            # Calculate cost for residential proxies
            if stats.proxy_type == "residential" and stats.cost_per_gb and data_transferred_mb > 0:
                cost = (data_transferred_mb / 1024) * stats.cost_per_gb
                self._monthly_cost += cost
        
        # Update database
        await self._update_proxy_stats(proxy_id, stats)
    
    async def _update_proxy_stats(self, proxy_id: int, stats: ProxyStats):
        """Update proxy statistics in database."""
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ProxyConfig)
                    .where(ProxyConfig.id == proxy_id)
                    .values(
                        success_rate=stats.success_rate,
                        avg_latency_ms=stats.avg_latency_ms,
                        last_used=stats.last_used,
                        last_success=stats.last_success,
                    )
                )
                await db.commit()
        except Exception as e:
            logger.debug(f"Error updating proxy stats for {proxy_id}: {e}")
    
    async def mark_site_blocked(self, domain: str, proxy_id: Optional[int] = None):
        """Mark a site as blocked and update protection level."""
        protection = self._get_site_protection(domain)
        protection.block_count += 1
        protection.last_blocked_at = datetime.utcnow()
        
        # Escalate protection level if multiple blocks
        if protection.block_count >= 5:
            protection.requires_residential = True
            protection.protection_level = "high"
        elif protection.block_count >= 3:
            protection.protection_level = "medium"
        
        # Mark proxy as failed if provided
        if proxy_id:
            await self.mark_proxy_result(proxy_id, success=False, latency_ms=0.0)
    
    async def get_proxy_stats(self) -> Dict[str, ProxyStats]:
        """Get statistics for all proxies."""
        async with self._stats_lock:
            return self._proxy_stats.copy()
    
    async def rotate_proxy_pool(self, domain: str):
        """Rotate proxy pool for a domain (mark current as cooldown)."""
        # This would implement cooldown logic
        # For now, just reload proxies to refresh health
        await self.load_proxies()
    
    def get_monthly_cost(self) -> float:
        """Get current monthly cost for residential proxies."""
        return self._monthly_cost
    
    def is_cost_limit_exceeded(self) -> bool:
        """Check if monthly cost limit is exceeded."""
        return self._monthly_cost >= self._cost_limit


# Global hybrid proxy manager instance
hybrid_proxy_manager = HybridProxyManager()
