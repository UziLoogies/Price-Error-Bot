"""Proxy health monitoring system.

Continuously monitors proxy health, removes blocked proxies,
tracks success rates and latency, and manages costs.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import ProxyConfig
from src.db.session import AsyncSessionLocal
from src.ingest.hybrid_proxy_manager import hybrid_proxy_manager

logger = logging.getLogger(__name__)


class ProxyHealthMonitor:
    """
    Monitors proxy health and automatically manages proxy pool.
    
    Features:
    - Continuous health checks
    - Automatic removal of blocked proxies
    - Success rate tracking
    - Latency monitoring
    - Cost tracking for residential proxies
    """
    
    def __init__(
        self,
        check_interval_seconds: int = 1800,  # 30 minutes
        health_check_url: str = "https://httpbin.org/ip",
        timeout: float = 10.0,
    ):
        """
        Initialize proxy health monitor.
        
        Args:
            check_interval_seconds: Interval between health checks
            health_check_url: URL to use for health checks
            timeout: Request timeout
        """
        self.check_interval = check_interval_seconds
        self.health_check_url = health_check_url
        self.timeout = timeout
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start health monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Proxy health monitor started")
    
    async def stop(self):
        """Stop health monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Proxy health monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self.check_all_proxies()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in proxy health monitor: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    async def check_all_proxies(self) -> Dict[str, int]:
        """
        Check health of all enabled proxies.
        
        Returns:
            Dict with check results
        """
        logger.info("Starting proxy health check")
        
        async with AsyncSessionLocal() as db:
            query = select(ProxyConfig).where(ProxyConfig.enabled == True)
            result = await db.execute(query)
            proxies = result.scalars().all()
        
        results = {
            "total": len(proxies),
            "healthy": 0,
            "unhealthy": 0,
            "disabled": 0,
        }
        
        # Check proxies in parallel (but limit concurrency)
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent checks
        
        async def check_proxy(proxy: ProxyConfig):
            async with semaphore:
                return await self.check_proxy_health(proxy)
        
        check_tasks = [check_proxy(proxy) for proxy in proxies]
        check_results = await asyncio.gather(*check_tasks, return_exceptions=True)
        
        for proxy, result in zip(proxies, check_results):
            if isinstance(result, Exception):
                logger.error(f"Error checking proxy {proxy.id}: {result}")
                results["unhealthy"] += 1
                await self._disable_proxy_if_needed(proxy.id, reason="Health check error")
            elif result:
                results["healthy"] += 1
            else:
                results["unhealthy"] += 1
                await self._disable_proxy_if_needed(proxy.id, reason="Health check failed")
        
        logger.info(
            f"Proxy health check complete: {results['healthy']} healthy, "
            f"{results['unhealthy']} unhealthy, {results['disabled']} disabled"
        )
        
        return results
    
    async def check_proxy_health(self, proxy: ProxyConfig) -> bool:
        """
        Check health of a single proxy.
        
        Args:
            proxy: Proxy configuration
            
        Returns:
            True if healthy, False otherwise
        """
        start_time = time.time()
        
        try:
            proxy_url = f"http://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}" if proxy.username else f"http://{proxy.host}:{proxy.port}"
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.health_check_url,
                    proxy=proxy_url,
                    follow_redirects=True,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                success = response.status_code == 200
                
                # Record result
                await hybrid_proxy_manager.mark_proxy_result(
                    proxy.id,
                    success,
                    latency_ms,
                )
                
                if success:
                    logger.debug(f"Proxy {proxy.id} ({proxy.host}) healthy (latency: {latency_ms:.0f}ms)")
                else:
                    logger.warning(f"Proxy {proxy.id} ({proxy.host}) unhealthy (status: {response.status_code})")
                
                return success
        
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.debug(f"Proxy {proxy.id} ({proxy.host}) health check failed: {e}")
            
            # Record failure
            await hybrid_proxy_manager.mark_proxy_result(
                proxy.id,
                False,
                latency_ms,
            )
            
            return False
    
    async def _disable_proxy_if_needed(self, proxy_id: int, reason: str):
        """Disable proxy if it has too many failures."""
        async with AsyncSessionLocal() as db:
            query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
            result = await db.execute(query)
            proxy = result.scalar_one_or_none()
            
            if not proxy:
                return
            
            # Check failure count
            if proxy.failure_count >= 5:
                await db.execute(
                    update(ProxyConfig)
                    .where(ProxyConfig.id == proxy_id)
                    .values(enabled=False)
                )
                await db.commit()
                logger.warning(f"Disabled proxy {proxy_id} due to {reason} (failure count: {proxy.failure_count})")
    
    async def get_health_summary(self) -> Dict[str, any]:
        """Get summary of proxy health."""
        async with AsyncSessionLocal() as db:
            query = select(ProxyConfig).where(ProxyConfig.enabled == True)
            result = await db.execute(query)
            proxies = result.scalars().all()
        
        summary = {
            "total_proxies": len(proxies),
            "by_type": {},
            "avg_success_rate": 0.0,
            "avg_latency_ms": 0.0,
            "unhealthy_count": 0,
        }
        
        total_success = 0.0
        total_latency = 0.0
        count = 0
        
        for proxy in proxies:
            proxy_type = proxy.proxy_type
            summary["by_type"][proxy_type] = summary["by_type"].get(proxy_type, 0) + 1
            
            if proxy.success_rate < 0.5:
                summary["unhealthy_count"] += 1
            
            total_success += proxy.success_rate
            total_latency += proxy.avg_latency_ms
            count += 1
        
        if count > 0:
            summary["avg_success_rate"] = total_success / count
            summary["avg_latency_ms"] = total_latency / count
        
        return summary


# Global proxy health monitor instance
proxy_health_monitor = ProxyHealthMonitor()
