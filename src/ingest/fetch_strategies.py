"""Fallback fetch strategies for resilient page fetching.

Implements a chain of fetch strategies that are tried in order until one succeeds.
Tracks success rates per store to optimize strategy selection over time.
"""

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

import httpx
from selectolax.parser import HTMLParser

from src.config import settings
from src.ingest.content_analyzer import content_analyzer, ContentAnalysis
from src.ingest.store_health import store_health
from src import metrics

logger = logging.getLogger(__name__)


class FetchStrategy(Enum):
    """Available fetch strategies in order of preference (cheapest to most expensive)."""
    STATIC = "static"
    STATIC_JS_HEADERS = "static_js_headers"
    HEADLESS = "headless"
    HEADLESS_STEALTH = "headless_stealth"


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    success: bool
    html: Optional[str]
    strategy_used: FetchStrategy
    duration_ms: float
    content_analysis: Optional[ContentAnalysis] = None
    error: Optional[str] = None
    status_code: Optional[int] = None


# User agents for static fetching
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Headers that mimic a JavaScript-capable browser
JS_CAPABLE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class FallbackFetcher:
    """
    Fetcher that tries multiple strategies with fallback support.
    
    Tracks success rates per store and optimizes strategy order based on
    historical performance.
    """
    
    def __init__(self):
        # Strategy success/failure counts per store
        self._strategy_success: Dict[str, Dict[FetchStrategy, int]] = defaultdict(lambda: defaultdict(int))
        self._strategy_failure: Dict[str, Dict[FetchStrategy, int]] = defaultdict(lambda: defaultdict(int))
        
        # HTTP clients (reused)
        self._static_client: Optional[httpx.AsyncClient] = None
        self._js_client: Optional[httpx.AsyncClient] = None
        
        # Playwright browser (lazy initialized)
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()
    
    async def _get_static_client(self) -> httpx.AsyncClient:
        """Get or create static HTTP client."""
        if self._static_client is None:
            self._static_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                },
            )
        return self._static_client
    
    async def _get_js_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with JS-capable headers."""
        if self._js_client is None:
            headers = {**JS_CAPABLE_HEADERS, "User-Agent": random.choice(USER_AGENTS)}
            self._js_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=headers,
            )
        return self._js_client
    
    async def _ensure_browser(self):
        """Ensure Playwright browser is initialized."""
        async with self._browser_lock:
            if self._playwright is None:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
    
    async def close(self):
        """Close all clients and browser."""
        if self._static_client:
            await self._static_client.aclose()
            self._static_client = None
        
        if self._js_client:
            await self._js_client.aclose()
            self._js_client = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
    
    def get_strategy_order(self, store: str) -> List[FetchStrategy]:
        """
        Get strategies ordered by success rate for this store.
        
        Args:
            store: Store identifier
            
        Returns:
            List of strategies in recommended order
        """
        if not settings.fallback_strategies_enabled:
            return [FetchStrategy.STATIC]
        
        # Default order from config
        default_order = [
            FetchStrategy(s) for s in settings.fallback_strategy_order
            if s in [e.value for e in FetchStrategy]
        ]
        
        if not default_order:
            default_order = [FetchStrategy.STATIC, FetchStrategy.HEADLESS]
        
        # Calculate success rates per strategy
        stats = self._strategy_success.get(store, {})
        fail_stats = self._strategy_failure.get(store, {})
        
        if not stats:
            return default_order
        
        def success_rate(strategy: FetchStrategy) -> float:
            successes = stats.get(strategy, 0)
            failures = fail_stats.get(strategy, 0)
            total = successes + failures
            if total == 0:
                return 0.5  # Unknown = neutral
            return successes / total
        
        # Sort by success rate (descending)
        sorted_strategies = sorted(default_order, key=success_rate, reverse=True)
        
        logger.debug(
            f"Strategy order for {store}: "
            f"{[s.value for s in sorted_strategies]} "
            f"(rates: {[(s.value, success_rate(s)) for s in sorted_strategies]})"
        )
        
        return sorted_strategies
    
    async def fetch_with_fallback(
        self,
        url: str,
        store: str,
        strategies: Optional[List[FetchStrategy]] = None,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """
        Fetch URL trying multiple strategies until one succeeds.
        
        Args:
            url: URL to fetch
            store: Store identifier
            strategies: Optional list of strategies to try (overrides defaults)
            conditional_headers: Optional headers for conditional requests (ETags)
            
        Returns:
            FetchResult with content or error
        """
        strategies = strategies or self.get_strategy_order(store)
        strategies = strategies[:settings.fallback_max_attempts]
        
        last_result: Optional[FetchResult] = None
        previous_strategy: Optional[FetchStrategy] = None
        
        for strategy in strategies:
            metrics.record_fetch_strategy_attempt(store, strategy.value)
            
            start_time = time.monotonic()
            result = await self._execute_strategy(
                strategy, url, store, conditional_headers
            )
            duration_ms = (time.monotonic() - start_time) * 1000
            result.duration_ms = duration_ms
            
            # Record store health
            await store_health.record_request(
                store=store,
                success=result.success,
                duration_ms=duration_ms,
                status_code=result.status_code,
                blocked=result.content_analysis.is_blocked if result.content_analysis else False,
                block_type=result.content_analysis.block_type if result.content_analysis else None,
            )
            
            if result.success:
                self._strategy_success[store][strategy] += 1
                metrics.record_fetch_strategy_success(store, strategy.value)
                
                if previous_strategy:
                    # We fell back from a failed strategy
                    metrics.record_fetch_fallback(
                        store, previous_strategy.value, strategy.value
                    )
                
                logger.debug(
                    f"Fetch succeeded for {store} using {strategy.value} "
                    f"({duration_ms:.0f}ms)"
                )
                return result
            else:
                self._strategy_failure[store][strategy] += 1
                logger.debug(
                    f"Fetch failed for {store} using {strategy.value}: {result.error}"
                )
                last_result = result
                previous_strategy = strategy
        
        # All strategies failed
        logger.warning(
            f"All {len(strategies)} strategies failed for {store} ({url})"
        )
        return FetchResult(
            success=False,
            html=None,
            strategy_used=strategies[-1] if strategies else FetchStrategy.STATIC,
            duration_ms=0,
            error="All strategies failed",
        )
    
    async def _execute_strategy(
        self,
        strategy: FetchStrategy,
        url: str,
        store: str,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """
        Execute a single fetch strategy.
        
        Args:
            strategy: Strategy to use
            url: URL to fetch
            store: Store identifier
            conditional_headers: Optional conditional request headers
            
        Returns:
            FetchResult
        """
        try:
            if strategy == FetchStrategy.STATIC:
                return await self._fetch_static(url, store, conditional_headers)
            
            elif strategy == FetchStrategy.STATIC_JS_HEADERS:
                return await self._fetch_static_js(url, store, conditional_headers)
            
            elif strategy == FetchStrategy.HEADLESS:
                return await self._fetch_headless(url, store, stealth=False)
            
            elif strategy == FetchStrategy.HEADLESS_STEALTH:
                return await self._fetch_headless(url, store, stealth=True)
            
            else:
                return FetchResult(
                    success=False,
                    html=None,
                    strategy_used=strategy,
                    duration_ms=0,
                    error=f"Unknown strategy: {strategy}",
                )
                
        except Exception as e:
            return FetchResult(
                success=False,
                html=None,
                strategy_used=strategy,
                duration_ms=0,
                error=str(e),
            )
    
    async def _fetch_static(
        self,
        url: str,
        store: str,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """Fetch using simple static HTTP request."""
        client = await self._get_static_client()
        
        headers = {}
        if conditional_headers:
            headers.update(conditional_headers)
        
        try:
            response = await client.get(url, headers=headers if headers else None)
            
            # Handle 304 Not Modified
            if response.status_code == 304:
                return FetchResult(
                    success=True,
                    html=None,  # Caller should use cached content
                    strategy_used=FetchStrategy.STATIC,
                    duration_ms=0,
                    status_code=304,
                )
            
            if response.status_code >= 400:
                return FetchResult(
                    success=False,
                    html=None,
                    strategy_used=FetchStrategy.STATIC,
                    duration_ms=0,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}",
                )
            
            html = response.text
            analysis = content_analyzer.analyze(html, store)
            
            if analysis.is_blocked:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=FetchStrategy.STATIC,
                    duration_ms=0,
                    content_analysis=analysis,
                    status_code=response.status_code,
                    error=f"Blocked: {analysis.block_type}",
                )
            
            if not analysis.is_valid:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=FetchStrategy.STATIC,
                    duration_ms=0,
                    content_analysis=analysis,
                    status_code=response.status_code,
                    error="Invalid content (no products found)",
                )
            
            return FetchResult(
                success=True,
                html=html,
                strategy_used=FetchStrategy.STATIC,
                duration_ms=0,
                content_analysis=analysis,
                status_code=response.status_code,
            )
            
        except httpx.TimeoutException:
            return FetchResult(
                success=False,
                html=None,
                strategy_used=FetchStrategy.STATIC,
                duration_ms=0,
                error="Timeout",
            )
        except Exception as e:
            return FetchResult(
                success=False,
                html=None,
                strategy_used=FetchStrategy.STATIC,
                duration_ms=0,
                error=str(e),
            )
    
    async def _fetch_static_js(
        self,
        url: str,
        store: str,
        conditional_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """Fetch using HTTP request with JS-capable headers."""
        client = await self._get_js_client()
        
        headers = {}
        if conditional_headers:
            headers.update(conditional_headers)
        
        try:
            response = await client.get(url, headers=headers if headers else None)
            
            if response.status_code == 304:
                return FetchResult(
                    success=True,
                    html=None,
                    strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                    duration_ms=0,
                    status_code=304,
                )
            
            if response.status_code >= 400:
                return FetchResult(
                    success=False,
                    html=None,
                    strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                    duration_ms=0,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}",
                )
            
            html = response.text
            analysis = content_analyzer.analyze(html, store)
            
            if analysis.is_blocked:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                    duration_ms=0,
                    content_analysis=analysis,
                    status_code=response.status_code,
                    error=f"Blocked: {analysis.block_type}",
                )
            
            if not analysis.is_valid:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                    duration_ms=0,
                    content_analysis=analysis,
                    status_code=response.status_code,
                    error="Invalid content",
                )
            
            return FetchResult(
                success=True,
                html=html,
                strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                duration_ms=0,
                content_analysis=analysis,
                status_code=response.status_code,
            )
            
        except httpx.TimeoutException:
            return FetchResult(
                success=False,
                html=None,
                strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                duration_ms=0,
                error="Timeout",
            )
        except Exception as e:
            return FetchResult(
                success=False,
                html=None,
                strategy_used=FetchStrategy.STATIC_JS_HEADERS,
                duration_ms=0,
                error=str(e),
            )
    
    async def _fetch_headless(
        self,
        url: str,
        store: str,
        stealth: bool = False,
    ) -> FetchResult:
        """Fetch using headless browser."""
        await self._ensure_browser()
        
        context = None
        page = None
        
        try:
            # Create context with optional stealth settings
            context_options = {
                "user_agent": random.choice(USER_AGENTS),
                "viewport": {"width": 1920, "height": 1080},
                "locale": "en-US",
                "timezone_id": "America/Chicago",
            }
            
            if stealth:
                # Additional stealth measures
                context_options["java_script_enabled"] = True
                context_options["bypass_csp"] = True
            
            context = await self._browser.new_context(**context_options)
            page = await context.new_page()
            
            # Additional stealth scripts
            if stealth:
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                """)
            
            # Navigate
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for content to render
            await asyncio.sleep(random.uniform(1, 2))
            
            # Get HTML
            html = await page.content()
            analysis = content_analyzer.analyze(html, store)
            
            strategy = FetchStrategy.HEADLESS_STEALTH if stealth else FetchStrategy.HEADLESS
            
            if analysis.is_blocked:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=strategy,
                    duration_ms=0,
                    content_analysis=analysis,
                    error=f"Blocked: {analysis.block_type}",
                )
            
            if not analysis.is_valid:
                return FetchResult(
                    success=False,
                    html=html,
                    strategy_used=strategy,
                    duration_ms=0,
                    content_analysis=analysis,
                    error="Invalid content",
                )
            
            return FetchResult(
                success=True,
                html=html,
                strategy_used=strategy,
                duration_ms=0,
                content_analysis=analysis,
            )
            
        except Exception as e:
            strategy = FetchStrategy.HEADLESS_STEALTH if stealth else FetchStrategy.HEADLESS
            return FetchResult(
                success=False,
                html=None,
                strategy_used=strategy,
                duration_ms=0,
                error=str(e),
            )
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
    
    def get_strategy_stats(self, store: Optional[str] = None) -> Dict[str, Any]:
        """
        Get strategy statistics.
        
        Args:
            store: Optional store to get stats for (None = all stores)
            
        Returns:
            Dict with strategy statistics
        """
        if store:
            success = dict(self._strategy_success.get(store, {}))
            failure = dict(self._strategy_failure.get(store, {}))
            
            stats = {}
            for strategy in FetchStrategy:
                s = success.get(strategy, 0)
                f = failure.get(strategy, 0)
                total = s + f
                stats[strategy.value] = {
                    "success": s,
                    "failure": f,
                    "total": total,
                    "rate": s / total if total > 0 else 0.0,
                }
            
            return {"store": store, "strategies": stats}
        
        # All stores
        all_stats = {}
        for store_name in set(self._strategy_success.keys()) | set(self._strategy_failure.keys()):
            all_stats[store_name] = self.get_strategy_stats(store_name)
        
        return all_stats


# Global instance
fallback_fetcher = FallbackFetcher()
