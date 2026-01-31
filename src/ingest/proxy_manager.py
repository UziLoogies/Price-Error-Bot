"""Proxy manager for rotating datacenter proxies."""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

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
    
    def set_session_factory(self, factory):
        """Set the database session factory for updating proxy stats."""
        self._db_session_factory = factory
    
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
                )
                for p in proxy_models
            ]
            
            logger.info(f"Loaded {len(self._proxies)} proxies")
    
    async def get_next_proxy(self, exclude_ids: Optional[set[int]] = None) -> Optional[ProxyInfo]:
        """
        Get next proxy in rotation (round-robin), excluding specified proxy IDs.
        
        Args:
            exclude_ids: Set of proxy IDs to exclude from selection
            
        Returns:
            ProxyInfo if available, None otherwise
        """
        async with self._lock:
            if not self._proxies:
                await self.load_proxies()
            
            if not self._proxies:
                logger.warning("No proxies available")
                return None
            
            # Filter out excluded proxies
            available_proxies = self._proxies
            if exclude_ids:
                available_proxies = [p for p in self._proxies if p.id not in exclude_ids]
                if not available_proxies:
                    logger.warning(f"No proxies available after excluding {len(exclude_ids)} proxies")
                    return None
            
            # Find next proxy starting from current index
            start_index = self._current_index
            attempts = 0
            while attempts < len(available_proxies):
                proxy = available_proxies[(start_index + attempts) % len(available_proxies)]
                if not exclude_ids or proxy.id not in exclude_ids:
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
        except Exception as e:
            logger.error(f"Failed to update proxy success: {e}")
    
    async def report_failure(self, proxy_id: int) -> None:
        """Report failed use of a proxy."""
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
    
    def has_proxies(self) -> bool:
        """Check if any proxies are available."""
        return len(self._proxies) > 0
    
    async def refresh(self) -> None:
        """Refresh proxy list from database."""
        async with self._lock:
            self._proxies = []
            self._current_index = 0
        await self.load_proxies()


# Global proxy rotator instance
proxy_rotator = ProxyRotator()
