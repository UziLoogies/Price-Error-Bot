"""HTTP/2 request batching for improved efficiency.

Batches multiple requests into single HTTP/2 connections,
groups requests by domain, and executes in parallel.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BatchedRequest:
    """A request in a batch."""
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    callback: Optional[callable] = None


@dataclass
class BatchResult:
    """Result of a batched request."""
    url: str
    success: bool
    response: Optional[httpx.Response] = None
    error: Optional[str] = None


class RequestBatcher:
    """
    Batches HTTP requests for efficiency using HTTP/2.
    
    Features:
    - Groups requests by domain
    - Executes batches in parallel
    - Optimizes batch size
    - Reuses HTTP/2 connections
    """
    
    def __init__(self, batch_size: int = None, timeout: float = 30.0):
        """
        Initialize request batcher.
        
        Args:
            batch_size: Optimal batch size (defaults to config)
            timeout: Request timeout
        """
        self.batch_size = batch_size or getattr(settings, 'batch_size', 10)
        self.timeout = timeout
        
        # Per-domain HTTP/2 clients
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._client_locks: Dict[str, asyncio.Lock] = {}
    
    async def _get_client(self, domain: str) -> httpx.AsyncClient:
        """Get or create HTTP/2 client for domain."""
        if domain not in self._clients:
            if domain not in self._client_locks:
                self._client_locks[domain] = asyncio.Lock()
            
            async with self._client_locks[domain]:
                if domain not in self._clients:
                    # Use HTTP/2 for better multiplexing
                    self._clients[domain] = httpx.AsyncClient(
                        http2=True,
                        timeout=self.timeout,
                        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                    )
        
        return self._clients[domain]
    
    async def batch_fetch(
        self,
        requests: List[BatchedRequest],
    ) -> List[BatchResult]:
        """
        Fetch multiple requests in batches.
        
        Args:
            requests: List of requests to batch
            
        Returns:
            List of BatchResult objects
        """
        # Group requests by domain
        by_domain: Dict[str, List[BatchedRequest]] = defaultdict(list)
        for req in requests:
            domain = urlparse(req.url).netloc
            by_domain[domain].append(req)
        
        # Process each domain's batch
        all_results = []
        domain_tasks = []
        
        for domain, domain_requests in by_domain.items():
            # Split into optimal batch sizes
            for i in range(0, len(domain_requests), self.batch_size):
                batch = domain_requests[i:i + self.batch_size]
                domain_tasks.append(self._fetch_batch(domain, batch))
        
        # Execute all batches in parallel
        batch_results = await asyncio.gather(*domain_tasks, return_exceptions=True)
        
        # Flatten results
        for result in batch_results:
            if isinstance(result, Exception):
                logger.error(f"Batch fetch error: {result}")
                continue
            all_results.extend(result)
        
        return all_results
    
    async def _fetch_batch(
        self,
        domain: str,
        requests: List[BatchedRequest],
    ) -> List[BatchResult]:
        """Fetch a batch of requests for a domain."""
        client = await self._get_client(domain)
        results = []
        
        # Create tasks for all requests in batch
        tasks = []
        for req in requests:
            task = self._fetch_single(client, req)
            tasks.append(task)
        
        # Execute all requests in parallel (HTTP/2 multiplexing)
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for req, response in zip(requests, responses):
            if isinstance(response, Exception):
                results.append(BatchResult(
                    url=req.url,
                    success=False,
                    error=str(response),
                ))
            else:
                results.append(BatchResult(
                    url=req.url,
                    success=response.status_code == 200,
                    response=response,
                ))
        
        return results
    
    async def _fetch_single(
        self,
        client: httpx.AsyncClient,
        request: BatchedRequest,
    ) -> httpx.Response:
        """Fetch a single request."""
        return await client.request(
            method=request.method,
            url=request.url,
            headers=request.headers,
        )
    
    async def close(self):
        """Close all HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self._client_locks.clear()


# Global request batcher instance
request_batcher = RequestBatcher()
