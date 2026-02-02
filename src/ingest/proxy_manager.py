"""Proxy manager for rotating datacenter proxies."""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ProxyInfo:
    """Proxy information for use in fetchers."""
    
    id: int
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    proxy_type: str = "datacenter"
    
    @property
    def url(self) -> str:
        """Get proxy URL for httpx."""
        if self.username and self.password:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"
    
    @property
    def playwright_config(self) -> dict:
        """Get proxy config for Playwright."""
        config = {"server": f"http://{self.host}:{self.port}"}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config


class ProxyRotator:
    """Manages rotating proxy pool with health tracking."""
    
    def __init__(self):
        self._proxies: list[ProxyInfo] = []
        self._current_index: int = 0
        self._lock = asyncio.Lock()
        self._db_session_factory = None
        # Track proxy cooldowns: proxy_id -> cooldown_until timestamp
        self._proxy_cooldowns: Dict[int, datetime] = {}
        # Track consecutive 403 failures: proxy_id -> count
        self._consecutive_403_failures: Dict[int, int] = {}
        # Configurable settings (loaded from config)
        self._load_config_settings()
    
    def set_session_factory(self, factory):
        """Set the database session factory for updating proxy stats."""
        self._db_session_factory = factory
    
    def _load_config_settings(self):
        """Load configurable settings from config."""
        from src.config import settings
        self._cooldown_duration_minutes: int = settings.proxy_cooldown_minutes
        self._max_consecutive_403s: int = settings.proxy_max_consecutive_403s
        self._cooldown_after_403_minutes: int = settings.proxy_cooldown_minutes
    
    async def load_proxies(self) -> None:
        """Load enabled proxies from database."""
        if not self._db_session_factory:
            logger.warning("No database session factory set, cannot load proxies")
            return
        
        from sqlalchemy import select
        from src.db.models import ProxyConfig
        
        async with self._db_session_factory() as db:
            query = select(ProxyConfig).where(
                ProxyConfig.enabled == True
            )
            result = await db.execute(query)
            proxy_models = result.scalars().all()
            
            self._proxies = [
                ProxyInfo(
                    id=p.id,
                    host=p.host,
                    port=p.port,
                    username=p.username,
                    password=p.password,
                    proxy_type=p.proxy_type or "datacenter",
                )
                for p in proxy_models
            ]
            
            logger.info(f"Loaded {len(self._proxies)} proxies")
    
    def _is_proxy_in_cooldown(self, proxy_id: int) -> bool:
        """Check if proxy is in cooldown period."""
        if proxy_id not in self._proxy_cooldowns:
            return False
        cooldown_until = self._proxy_cooldowns[proxy_id]
        if datetime.utcnow() < cooldown_until:
            return True
        # Cooldown expired, remove it
        del self._proxy_cooldowns[proxy_id]
        return False
    
    def _is_proxy_disabled(self, proxy_id: int) -> bool:
        """Check if proxy is disabled due to consecutive 403 failures."""
        consecutive_403s = self._consecutive_403_failures.get(proxy_id, 0)
        return consecutive_403s >= self._max_consecutive_403s
    
    async def get_next_proxy(
        self,
        exclude_ids: Optional[set[int]] = None,
        proxy_type: Optional[str] = None,
    ) -> Optional[ProxyInfo]:
        """
        Get next proxy in rotation (round-robin), excluding specified proxy IDs and proxies in cooldown.
        
        Args:
            exclude_ids: Set of proxy IDs to exclude from selection
            proxy_type: Optional proxy type filter (datacenter/residential/isp)
            
        Returns:
            ProxyInfo if available, None otherwise
        """
        async with self._lock:
            if not self._proxies:
                await self.load_proxies()
            
            if not self._proxies:
                logger.warning("No proxies available")
                return None
            
            # Build exclusion set including cooldown and disabled proxies
            now = datetime.utcnow()
            excluded = set(exclude_ids) if exclude_ids else set()
            
            # Add proxies in cooldown to exclusion
            for proxy_id, cooldown_until in list(self._proxy_cooldowns.items()):
                if now < cooldown_until:
                    excluded.add(proxy_id)
                else:
                    # Cooldown expired, clean up
                    del self._proxy_cooldowns[proxy_id]
            
            # Add disabled proxies to exclusion
            for proxy_id, consecutive_403s in self._consecutive_403_failures.items():
                if consecutive_403s >= self._max_consecutive_403s:
                    excluded.add(proxy_id)
            
            # Filter out excluded proxies and proxy type if requested
            available_proxies = [
                p for p in self._proxies
                if p.id not in excluded and (not proxy_type or p.proxy_type == proxy_type)
            ]
            
            if not available_proxies:
                logger.warning(
                    f"No proxies available after excluding {len(excluded)} proxies "
                    f"({len([p for p in self._proxies if p.id in excluded and self._is_proxy_in_cooldown(p.id)])} in cooldown, "
                    f"{len([p for p in self._proxies if self._is_proxy_disabled(p.id)])} disabled)"
                )
                return None
            
            # Find next proxy starting from current index
            start_index = self._current_index
            attempts = 0
            while attempts < len(available_proxies):
                proxy = available_proxies[(start_index + attempts) % len(available_proxies)]
                if proxy.id not in excluded:
                    # Update current index to point after this proxy
                    self._current_index = (self._proxies.index(proxy) + 1) % len(self._proxies)
                    # Update last_used in database
                    await self._update_last_used(proxy.id)
                    return proxy
                attempts += 1
            
            # Fallback: return first available proxy
            if available_proxies:
                proxy = available_proxies[0]
                self._current_index = (self._proxies.index(proxy) + 1) % len(self._proxies)
                await self._update_last_used(proxy.id)
                return proxy
            
            return None
    
    async def get_random_proxy(self) -> Optional[ProxyInfo]:
        """Get a random proxy from the pool."""
        async with self._lock:
            if not self._proxies:
                await self.load_proxies()
            
            if not self._proxies:
                return None
            
            proxy = random.choice(self._proxies)
            await self._update_last_used(proxy.id)
            return proxy
    
    async def report_success(self, proxy_id: int) -> None:
        """Report successful use of a proxy."""
        if not self._db_session_factory:
            return
        
        from sqlalchemy import select
        from src.db.models import ProxyConfig
        
        try:
            async with self._db_session_factory() as db:
                query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
                result = await db.execute(query)
                proxy = result.scalar_one_or_none()
                
                if proxy:
                    proxy.last_success = datetime.utcnow()
                    proxy.failure_count = 0  # Reset on success
                    await db.commit()
            
            # Reset consecutive 403 failures on success
            async with self._lock:
                if proxy_id in self._consecutive_403_failures:
                    del self._consecutive_403_failures[proxy_id]
                # Clear cooldown if present
                if proxy_id in self._proxy_cooldowns:
                    del self._proxy_cooldowns[proxy_id]
            
            # Update metrics
            from src import metrics
            metrics.update_proxy_consecutive_403s(proxy_id, 0)
            metrics.update_proxy_cooldown(proxy_id, False)
        except Exception as e:
            logger.error(f"Failed to update proxy success: {e}")
    
    async def report_failure(self, proxy_id: int, error_type: str = "generic") -> None:
        """
        Report failed use of a proxy.
        
        Args:
            proxy_id: ID of the proxy that failed
            error_type: Type of error ('403', 'timeout', 'connect', 'generic')
        """
        if not self._db_session_factory:
            return
        
        from sqlalchemy import select
        from src.db.models import ProxyConfig
        
        try:
            async with self._db_session_factory() as db:
                query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
                result = await db.execute(query)
                proxy = result.scalar_one_or_none()
                
                if proxy:
                    proxy.failure_count += 1
                    # Note: Proxies remain enabled regardless of failure count
                    # to ensure 24/7 operation. Users can manually disable via UI.
                    logger.debug(
                        f"Proxy {proxy.host}:{proxy.port} failure count: "
                        f"{proxy.failure_count} (still enabled)"
                    )
                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to update proxy failure: {e}")
    
    async def report_403_failure(self, proxy_id: int) -> None:
        """
        Report a 403 Forbidden failure for a proxy.
        This triggers cooldown and tracks consecutive 403s.
        """
        async with self._lock:
            # Increment consecutive 403 counter
            self._consecutive_403_failures[proxy_id] = (
                self._consecutive_403_failures.get(proxy_id, 0) + 1
            )
            consecutive_403s = self._consecutive_403_failures[proxy_id]
            
            # Set cooldown period (15-30 minutes, default 20)
            cooldown_until = datetime.utcnow() + timedelta(
                minutes=self._cooldown_after_403_minutes
            )
            self._proxy_cooldowns[proxy_id] = cooldown_until
            
            # Get proxy info for logging
            proxy_info = None
            for p in self._proxies:
                if p.id == proxy_id:
                    proxy_info = p
                    break
            
            if proxy_info:
                if consecutive_403s >= self._max_consecutive_403s:
                    logger.warning(
                        f"Proxy {proxy_info.host}:{proxy_info.port} disabled after "
                        f"{consecutive_403s} consecutive 403 failures. "
                        f"Will be excluded from rotation."
                    )
                else:
                    logger.warning(
                        f"Proxy {proxy_info.host}:{proxy_info.port} received 403, "
                        f"consecutive failures: {consecutive_403s}/{self._max_consecutive_403s}. "
                        f"Cooldown until {cooldown_until.strftime('%H:%M:%S')}"
                    )
            
            # Record metrics
            from src import metrics
            metrics.record_proxy_403_failure(proxy_id)
            metrics.update_proxy_consecutive_403s(proxy_id, consecutive_403s)
            metrics.update_proxy_cooldown(proxy_id, True)
        
        # Also report as generic failure for database tracking
        await self.report_failure(proxy_id, error_type="403")
    
    async def _update_last_used(self, proxy_id: int) -> None:
        """Update last_used timestamp for a proxy."""
        if not self._db_session_factory:
            return
        
        from sqlalchemy import select
        from src.db.models import ProxyConfig
        
        try:
            async with self._db_session_factory() as db:
                query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
                result = await db.execute(query)
                proxy = result.scalar_one_or_none()
                
                if proxy:
                    proxy.last_used = datetime.utcnow()
                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to update proxy last_used: {e}")
    
    async def test_proxy(self, proxy: ProxyInfo, timeout: float = 10.0) -> bool:
        """
        Test if a proxy is working.
        
        Args:
            proxy: Proxy to test
            timeout: Request timeout in seconds
            
        Returns:
            True if proxy is working, False otherwise
        """
        test_url = "https://httpbin.org/ip"
        
        try:
            async with httpx.AsyncClient(
                proxy=proxy.url,
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(test_url)
                
                if response.status_code == 200:
                    logger.info(f"Proxy {proxy.host}:{proxy.port} is working")
                    return True
                else:
                    logger.warning(
                        f"Proxy {proxy.host}:{proxy.port} returned status "
                        f"{response.status_code}"
                    )
                    return False
                    
        except Exception as e:
            logger.error(f"Proxy {proxy.host}:{proxy.port} test failed: {e}")
            return False
    
    @property
    def proxy_count(self) -> int:
        """Get number of available proxies."""
        return len(self._proxies)
    
    def has_proxies(self, proxy_type: Optional[str] = None) -> bool:
        """Check if any proxies are available (optionally by type)."""
        if not self._proxies:
            return False
        if proxy_type:
            return any(p.proxy_type == proxy_type for p in self._proxies)
        return len(self._proxies) > 0
    
    async def refresh(self) -> None:
        """Refresh proxy list from database."""
        async with self._lock:
            self._proxies = []
            self._current_index = 0
            # Note: We keep cooldowns and consecutive failures in memory
            # They will be cleared when proxies succeed or cooldowns expire
        await self.load_proxies()
    
    def set_cooldown_duration(self, minutes: int) -> None:
        """Set cooldown duration after 403 errors (15-30 minutes recommended)."""
        self._cooldown_after_403_minutes = max(15, min(30, minutes))
    
    def set_max_consecutive_403s(self, count: int) -> None:
        """Set maximum consecutive 403 failures before disabling proxy."""
        self._max_consecutive_403s = max(1, count)


# Global proxy rotator instance
proxy_rotator = ProxyRotator()
