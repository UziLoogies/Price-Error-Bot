"""High-speed async scraper pool for concurrent page fetching.

Implements dynamic worker pool with priority queue, connection reuse,
automatic retry, and request batching for maximum throughput.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional, List, Dict, Any, Callable, Awaitable
from urllib.parse import urlparse

import httpx

from src.config import settings
from src.ingest.proxy_manager import proxy_rotator, ProxyInfo
from src.ingest.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Task priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class FetchTask:
    """A single fetch task."""
    url: str
    priority: Priority = Priority.NORMAL
    store: str = ""
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.utcnow)
    callback: Optional[Callable[[Any], Awaitable[None]]] = None
    
    def __lt__(self, other):
        """Compare by priority (higher priority first)."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.created_at < other.created_at


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    url: str
    success: bool
    html: Optional[str] = None
    status_code: Optional[int] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    proxy_used: Optional[ProxyInfo] = None
    retry_count: int = 0
    headers: Optional[Dict[str, str]] = None


@dataclass
class PoolStats:
    """Statistics for the scraper pool."""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    active_workers: int = 0
    queue_size: int = 0
    avg_latency_ms: float = 0.0
    requests_per_second: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0


class ScraperPool:
    """
    High-performance async scraper pool with priority queue and connection reuse.
    
    Features:
    - Dynamic worker pool with configurable concurrency
    - Priority-based task queue
    - Connection reuse across requests
    - Automatic retry with exponential backoff
    - Request batching for efficiency
    """
    
    def __init__(
        self,
        pool_size: int = None,
        max_connections: int = None,
        timeout: float = 30.0,
    ):
        """
        Initialize scraper pool.
        
        Args:
            pool_size: Number of concurrent workers (defaults to config)
            max_connections: Max connections per domain (defaults to config)
            timeout: Request timeout in seconds
        """
        self.pool_size = pool_size or getattr(settings, 'scraper_pool_size', 50)
        self.max_connections = max_connections or getattr(settings, 'http_max_connections', 100)
        self.timeout = timeout
        
        # Task queue (priority queue)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._workers: List[asyncio.Task] = []
        self._running = False
        
        # Per-domain HTTP clients for connection reuse
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._client_locks: Dict[str, asyncio.Lock] = {}
        
        # Statistics
        self._stats = PoolStats()
        self._stats_lock = asyncio.Lock()
        self._start_time = time.monotonic()
        self._last_request_time = time.monotonic()
        self._request_count = 0
        
        # Cache for results (optional) - stores (result, timestamp)
        self._result_cache: Dict[str, tuple[FetchResult, float]] = {}
        self._cache_ttl = 60.0  # 1 minute cache
        
    async def start(self):
        """Start the worker pool."""
        if self._running:
            return
        
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(f"worker-{i}"))
            for i in range(self.pool_size)
        ]
        logger.info(f"Started scraper pool with {self.pool_size} workers")
    
    async def stop(self):
        """Stop the worker pool and close connections."""
        self._running = False
        
        # Wait for queue to drain
        while not self._queue.empty():
            await asyncio.sleep(0.1)
        
        # Cancel workers
        for worker in self._workers:
            worker.cancel()
        
        await asyncio.gather(*self._workers, return_exceptions=True)
        
        # Close HTTP clients
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        
        logger.info("Stopped scraper pool")
    
    async def _get_client(self, domain: str) -> httpx.AsyncClient:
        """Get or create HTTP client for a domain (connection reuse)."""
        if domain not in self._clients:
            if domain not in self._client_locks:
                self._client_locks[domain] = asyncio.Lock()
            
            async with self._client_locks[domain]:
                # Double-check after acquiring lock
                if domain not in self._clients:
                    limits = httpx.Limits(
                        max_keepalive_connections=getattr(settings, 'connection_keepalive', 20),
                        max_connections=self.max_connections,
                    )
                    self._clients[domain] = httpx.AsyncClient(
                        timeout=self.timeout,
                        limits=limits,
                        follow_redirects=True,
                    )
        
        return self._clients[domain]
    
    async def fetch_batch(
        self,
        urls: List[str],
        priority: Priority = Priority.NORMAL,
        store: str = "",
        max_retries: int = 3,
    ) -> List[FetchResult]:
        """
        Fetch multiple URLs in parallel using the pool.
        
        Args:
            urls: List of URLs to fetch
            priority: Priority level for these tasks
            store: Store identifier
            max_retries: Maximum retry attempts per URL
            
        Returns:
            List of FetchResult objects
        """
        if not self._running:
            await self.start()
        
        # Create tasks
        tasks = [
            FetchTask(
                url=url,
                priority=priority,
                store=store,
                max_retries=max_retries,
            )
            for url in urls
        ]
        
        # Add to queue
        for task in tasks:
            await self._queue.put((task.priority.value, task))
            async with self._stats_lock:
                self._stats.total_tasks += 1
                self._stats.queue_size += 1
        
        # Wait for completion
        results = []
        pending = {task.url: asyncio.Event() for task in tasks}
        result_map = {}
        
        def set_result(url: str, result: FetchResult):
            result_map[url] = result
            pending[url].set()
        
        # Store callbacks
        for task in tasks:
            task.callback = lambda r, url=task.url: set_result(url, r)
        
        # Wait for all to complete
        await asyncio.gather(*[event.wait() for event in pending.values()])
        
        # Return results in original order
        for url in urls:
            results.append(result_map.get(url, FetchResult(url=url, success=False, error="No result")))
        
        return results
    
    async def fetch_with_retry(
        self,
        url: str,
        priority: Priority = Priority.NORMAL,
        store: str = "",
        max_retries: int = 3,
    ) -> FetchResult:
        """
        Fetch a single URL with automatic retry.
        
        Args:
            url: URL to fetch
            priority: Priority level
            store: Store identifier
            max_retries: Maximum retry attempts
            
        Returns:
            FetchResult object
        """
        results = await self.fetch_batch([url], priority, store, max_retries)
        return results[0] if results else FetchResult(url=url, success=False, error="No result")
    
    async def _worker(self, worker_id: str):
        """Worker coroutine that processes tasks from the queue."""
        logger.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Get task from queue (with timeout to allow checking _running)
                try:
                    priority, task = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                async with self._stats_lock:
                    self._stats.queue_size -= 1
                    self._stats.active_workers += 1
                
                try:
                    result = await self._fetch_task(task)
                    
                    # Update stats
                    async with self._stats_lock:
                        self._stats.completed_tasks += 1
                        if not result.success:
                            self._stats.failed_tasks += 1
                        self._stats.active_workers -= 1
                        self._stats.avg_latency_ms = (
                            (self._stats.avg_latency_ms * (self._stats.completed_tasks - 1) + result.latency_ms) /
                            self._stats.completed_tasks
                        )
                    
                    # Call callback if provided
                    if task.callback:
                        try:
                            await task.callback(result)
                        except Exception as e:
                            logger.error(f"Callback error for {task.url}: {e}")
                
                except Exception as e:
                    logger.error(f"Worker {worker_id} error processing {task.url}: {e}")
                    async with self._stats_lock:
                        self._stats.failed_tasks += 1
                        self._stats.active_workers -= 1
                
                finally:
                    self._queue.task_done()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
        
        logger.debug(f"Worker {worker_id} stopped")
    
    async def _fetch_task(self, task: FetchTask) -> FetchResult:
        """Fetch a single task."""
        start_time = time.monotonic()
        
        # Check cache
        cache_key = f"{task.url}:{task.store}"
        if cache_key in self._result_cache:
            cached_result, cached_time = self._result_cache[cache_key]
            # Check if cache is still valid
            if time.monotonic() - cached_time < self._cache_ttl:
                async with self._stats_lock:
                    self._stats.cache_hits += 1
                return cached_result
        
        async with self._stats_lock:
            self._stats.cache_misses += 1
        
        # Get domain for client selection
        domain = urlparse(task.url).netloc
        
        # Rate limiting
        await rate_limiter.acquire_adaptive(domain)
        
        # Get proxy
        proxy = await proxy_rotator.get_next_proxy()
        proxy_url = proxy.url if proxy else None
        
        # Get HTTP client
        client = await self._get_client(domain)
        
        # Build headers
        headers = self._build_headers(task.store)
        
        # Fetch with retry
        last_error = None
        for attempt in range(task.max_retries + 1):
            try:
                response = await client.get(
                    task.url,
                    headers=headers,
                    proxy=proxy_url,
                    follow_redirects=True,
                )
                
                latency_ms = (time.monotonic() - start_time) * 1000
                
                # Update request stats
                self._request_count += 1
                now = time.monotonic()
                elapsed = now - self._last_request_time
                if elapsed > 0:
                    self._stats.requests_per_second = self._request_count / elapsed
                
                result = FetchResult(
                    url=task.url,
                    success=response.status_code == 200,
                    html=response.text if response.status_code == 200 else None,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    proxy_used=proxy,
                    retry_count=attempt,
                    headers=dict(response.headers),
                )
                
                # Cache successful results
                if result.success:
                    self._result_cache[cache_key] = (result, time.monotonic())
                    # Clean old cache entries periodically
                    if len(self._result_cache) > 1000:
                        current_time = time.monotonic()
                        self._result_cache = {
                            k: v for k, v in self._result_cache.items()
                            if current_time - v[1] < self._cache_ttl
                        }
                
                return result
            
            except Exception as e:
                last_error = str(e)
                if attempt < task.max_retries:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                    logger.debug(f"Retry {attempt + 1}/{task.max_retries} for {task.url}")
        
        # All retries failed
        latency_ms = (time.monotonic() - start_time) * 1000
        return FetchResult(
            url=task.url,
            success=False,
            error=last_error or "Unknown error",
            latency_ms=latency_ms,
            retry_count=task.max_retries,
        )
    
    def _build_headers(self, store: str) -> Dict[str, str]:
        """Build realistic headers for requests."""
        import random
        from src.ingest.category_scanner import USER_AGENTS
        
        user_agent = random.choice(USER_AGENTS)
        
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        }
    
    def get_pool_stats(self) -> PoolStats:
        """Get current pool statistics."""
        async def _get():
            async with self._stats_lock:
                return PoolStats(
                    total_tasks=self._stats.total_tasks,
                    completed_tasks=self._stats.completed_tasks,
                    failed_tasks=self._stats.failed_tasks,
                    active_workers=self._stats.active_workers,
                    queue_size=self._queue.qsize(),
                    avg_latency_ms=self._stats.avg_latency_ms,
                    requests_per_second=self._stats.requests_per_second,
                    cache_hits=self._stats.cache_hits,
                    cache_misses=self._stats.cache_misses,
                )
        
        # For sync access, create a new event loop if needed
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, return current stats (may be slightly stale)
                return PoolStats(
                    total_tasks=self._stats.total_tasks,
                    completed_tasks=self._stats.completed_tasks,
                    failed_tasks=self._stats.failed_tasks,
                    active_workers=self._stats.active_workers,
                    queue_size=self._queue.qsize(),
                    avg_latency_ms=self._stats.avg_latency_ms,
                    requests_per_second=self._stats.requests_per_second,
                    cache_hits=self._stats.cache_hits,
                    cache_misses=self._stats.cache_misses,
                )
            else:
                return loop.run_until_complete(_get())
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(_get())


# Global scraper pool instance
scraper_pool = ScraperPool()
