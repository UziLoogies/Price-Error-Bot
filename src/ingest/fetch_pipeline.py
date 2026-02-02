"""Centralized fetch pipeline with typed outcomes and content triage."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Set
from urllib.parse import urlparse

import httpx

from src.ingest.http_client import (
    fetch_with_policy,
    get_policy_for_store,
    BlockedError,
    PermanentURLError,
    RateLimitedError,
    TransientFetchError,
    SitePolicy,
)
from src.ingest.content_analyzer import content_analyzer
from src.ingest.json_extractor import extract_embedded_json, extract_products_from_json
from src.ingest.debug_bundle import debug_bundle_writer
from src.config import settings

logger = logging.getLogger(__name__)


class FetchOutcome(str, Enum):
    """Typed outcomes for fetch operations."""
    
    OK_HTML = "ok_html"  # Valid HTML response
    OK_JSON = "ok_json"  # Valid JSON response (from embedded data)
    BLOCKED = "blocked"  # Access blocked (403, /blocked redirect, bot challenge)
    NOT_FOUND = "not_found"  # URL permanently invalid (404)
    TIMEOUT = "timeout"  # Request timeout
    RETRYABLE_NETWORK = "retryable_network"  # Network error (retryable)
    PARSING_EMPTY = "parsing_empty"  # Valid response but parser found 0 products
    PARTIAL_CONTENT_SUSPECT = "partial_content_suspect"  # HTTP 206 or truncated content


@dataclass
class ContentTriageResult:
    """Result of content triage analysis."""
    
    is_blocked: bool
    block_type: Optional[str]
    has_json_data: bool
    json_data: Optional[Dict[str, Any]]
    is_partial: bool
    product_indicators_found: int
    confidence: float
    reason: str


@dataclass
class FetchResult:
    """Result of a fetch operation with typed outcome."""
    
    outcome: FetchOutcome
    html: Optional[str] = None
    json_data: Optional[Dict[str, Any]] = None
    response: Optional[httpx.Response] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    triage_result: Optional[ContentTriageResult] = None


class FetchPipeline:
    """
    Centralized fetch pipeline with typed outcomes and content triage.
    
    Features:
    - Typed outcome classification
    - Content triage before parsing
    - Bot interstitial detection
    - JSON-inlined data extraction
    - Partial content detection
    """
    
    def __init__(self):
        """Initialize fetch pipeline."""
        pass
    
    async def fetch_page(
        self,
        url: str,
        store: str,
        client: httpx.AsyncClient,
        proxy: Optional[Any] = None,
        session_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        """
        Fetch a page and return typed result.
        
        Args:
            url: URL to fetch
            store: Store identifier
            client: httpx AsyncClient instance
            proxy: Optional proxy info (for metadata)
            session_key: Optional session key (for metadata)
            headers: Optional additional headers
            
        Returns:
            FetchResult with typed outcome
        """
        policy = get_policy_for_store(store)
        
        try:
            # Attempt fetch with policy
            response = await fetch_with_policy(client, url, policy, headers=headers)
            
            # Get HTML content
            html = response.text
            
            # Classify response
            outcome = await self.classify_response(response, html, store, policy)
            
            # Perform content triage
            triage_result = await self.triage_content(html, store, url, response)
            
            # Update outcome based on triage if needed
            if triage_result.is_blocked and outcome == FetchOutcome.OK_HTML:
                outcome = FetchOutcome.BLOCKED
                logger.debug(f"Content triage detected block: {triage_result.block_type}")
            
            # Check for JSON data
            json_data = None
            if triage_result.has_json_data:
                json_data = triage_result.json_data
                if outcome == FetchOutcome.OK_HTML and json_data:
                    # If we have JSON data, mark as OK_JSON
                    outcome = FetchOutcome.OK_JSON
            
            # Check for partial content
            if triage_result.is_partial:
                if policy.treat_206_as_suspect or response.status_code == 206:
                    outcome = FetchOutcome.PARTIAL_CONTENT_SUSPECT
            
            # Check for parsing empty (valid response but no products)
            if outcome == FetchOutcome.OK_HTML and triage_result.product_indicators_found == 0:
                outcome = FetchOutcome.PARSING_EMPTY
            
            # Build metadata
            metadata = {
                "status_code": response.status_code,
                "final_url": str(response.url),
                "content_length": len(html),
                "store": store,
                "proxy_id": proxy.id if proxy else None,
                "session_key": session_key,
                "triage_confidence": triage_result.confidence,
                "product_indicators": triage_result.product_indicators_found,
            }
            
            result = FetchResult(
                outcome=outcome,
                html=html,
                json_data=json_data,
                response=response,
                metadata=metadata,
                triage_result=triage_result,
            )
            
            # Write debug bundle for failure outcomes
            if outcome in (FetchOutcome.BLOCKED, FetchOutcome.NOT_FOUND, FetchOutcome.TIMEOUT, FetchOutcome.PARSING_EMPTY):
                try:
                    await debug_bundle_writer.write_bundle(
                        outcome=outcome,
                        store=store,
                        url=url,
                        html=html,
                        response=response,
                        metadata=metadata,
                    )
                except Exception as bundle_error:
                    logger.warning(f"Failed to write debug bundle: {bundle_error}")
            
            return result
            
        except BlockedError as e:
            # Access blocked
            logger.warning(f"Blocked for {store}: {e}")
            result = FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                    "blocked_reason": str(e),
                },
            )
            # Write debug bundle
            try:
                await debug_bundle_writer.write_bundle(
                    outcome=FetchOutcome.BLOCKED,
                    store=store,
                    url=url,
                    html=None,
                    response=None,
                    metadata=result.metadata,
                )
            except Exception as bundle_error:
                logger.warning(f"Failed to write debug bundle: {bundle_error}")
            return result
            
        except PermanentURLError as e:
            # 404 Not Found
            logger.warning(f"404 for {store}: {e}")
            result = FetchResult(
                outcome=FetchOutcome.NOT_FOUND,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                },
            )
            # Write debug bundle
            try:
                await debug_bundle_writer.write_bundle(
                    outcome=FetchOutcome.NOT_FOUND,
                    store=store,
                    url=url,
                    html=None,
                    response=None,
                    metadata=result.metadata,
                )
            except Exception as bundle_error:
                logger.warning(f"Failed to write debug bundle: {bundle_error}")
            return result
            
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            # Timeout
            logger.warning(f"Timeout for {store}: {e}")
            result = FetchResult(
                outcome=FetchOutcome.TIMEOUT,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                    "timeout_type": type(e).__name__,
                },
            )
            # Write debug bundle
            try:
                await debug_bundle_writer.write_bundle(
                    outcome=FetchOutcome.TIMEOUT,
                    store=store,
                    url=url,
                    html=None,
                    response=None,
                    metadata=result.metadata,
                )
            except Exception as bundle_error:
                logger.warning(f"Failed to write debug bundle: {bundle_error}")
            return result
            
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.PoolTimeout) as e:
            # Retryable network error
            logger.warning(f"Network error for {store}: {e}")
            return FetchResult(
                outcome=FetchOutcome.RETRYABLE_NETWORK,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                    "error_type": type(e).__name__,
                },
            )
            
        except TransientFetchError as e:
            # Transient error after retries
            logger.warning(f"Transient error for {store}: {e}")
            return FetchResult(
                outcome=FetchOutcome.RETRYABLE_NETWORK,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                },
            )
            
        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error fetching {url}: {e}", exc_info=True)
            return FetchResult(
                outcome=FetchOutcome.RETRYABLE_NETWORK,
                error=str(e),
                metadata={
                    "store": store,
                    "proxy_id": proxy.id if proxy else None,
                    "session_key": session_key,
                    "error_type": type(e).__name__,
                },
            )
    
    async def classify_response(
        self,
        response: httpx.Response,
        html: str,
        store: str,
        policy: SitePolicy,
    ) -> FetchOutcome:
        """
        Classify response into typed outcome.
        
        Args:
            response: HTTP response
            html: Response HTML content
            store: Store identifier
            policy: Site policy
            
        Returns:
            FetchOutcome enum value
        """
        status_code = response.status_code
        final_url = str(response.url).lower()
        
        # Check for /blocked redirect (Walmart and others)
        if "/blocked" in final_url:
            logger.debug(f"Detected /blocked redirect for {store}")
            return FetchOutcome.BLOCKED
        
        # Check blocked URL patterns from policy
        if hasattr(policy, 'blocked_url_patterns') and policy.blocked_url_patterns:
            for pattern in policy.blocked_url_patterns:
                if pattern.lower() in final_url:
                    logger.debug(f"Detected blocked URL pattern '{pattern}' for {store}")
                    return FetchOutcome.BLOCKED
        
        # Handle status codes
        if status_code == 404:
            return FetchOutcome.NOT_FOUND
        
        if status_code == 206:
            # Partial content - check if suspect
            if policy.treat_206_as_suspect:
                return FetchOutcome.PARTIAL_CONTENT_SUSPECT
            # Check if Range header was sent (if not, 206 is suspicious)
            if "range" not in {k.lower(): v for k, v in response.request.headers.items()}:
                return FetchOutcome.PARTIAL_CONTENT_SUSPECT
        
        if status_code in (401, 403):
            return FetchOutcome.BLOCKED
        
        if 200 <= status_code < 300:
            # Success - will be refined by content triage
            return FetchOutcome.OK_HTML
        
        # Other status codes - treat as retryable
        return FetchOutcome.RETRYABLE_NETWORK
    
    async def triage_content(
        self,
        html: str,
        store: str,
        url: str,
        response: Optional[httpx.Response] = None,
    ) -> ContentTriageResult:
        """
        Perform content triage to detect bot interstitials, JSON data, and partial content.
        
        Args:
            html: HTML content
            store: Store identifier
            url: Original URL
            response: Optional HTTP response
            
        Returns:
            ContentTriageResult with analysis
        """
        if not html:
            return ContentTriageResult(
                is_blocked=False,
                block_type=None,
                has_json_data=False,
                json_data=None,
                is_partial=False,
                product_indicators_found=0,
                confidence=0.0,
                reason="Empty HTML content",
            )
        
        # Use content analyzer for bot detection
        analysis = content_analyzer.analyze(html, store)
        
        # Check for JSON-inlined data
        json_data = None
        has_json = False
        embedded_json = extract_embedded_json(html)
        
        if embedded_json.get("next_data") or embedded_json.get("initial_state") or embedded_json.get("json_ld"):
            has_json = True
            json_data = embedded_json
        
        # Check for partial content
        is_partial = False
        if response:
            # Check content-length mismatch
            content_length_header = response.headers.get("Content-Length")
            if content_length_header:
                try:
                    expected_length = int(content_length_header)
                    # Use byte length, not character count (Content-Length is in bytes)
                    actual_length = len(response.content) if hasattr(response, 'content') else len(html.encode('utf-8'))
                    if actual_length < expected_length * 0.9:  # More than 10% missing
                        is_partial = True
                except (ValueError, TypeError):
                    pass
            
            # Check for 206 status
            if response.status_code == 206:
                is_partial = True
        
        # Count product indicators from analysis
        product_indicators = analysis.product_count_estimate
        
        # Build reason string
        reasons = []
        if analysis.is_blocked:
            reasons.append(f"Blocked: {analysis.block_type}")
        if has_json:
            reasons.append("JSON data found")
        if is_partial:
            reasons.append("Partial content detected")
        if product_indicators == 0:
            reasons.append("No product indicators")
        
        reason = "; ".join(reasons) if reasons else "Content appears valid"
        
        return ContentTriageResult(
            is_blocked=analysis.is_blocked,
            block_type=analysis.block_type,
            has_json_data=has_json,
            json_data=json_data,
            is_partial=is_partial,
            product_indicators_found=product_indicators,
            confidence=analysis.confidence,
            reason=reason,
        )


# Global fetch pipeline instance
fetch_pipeline = FetchPipeline()
