"""Debug bundle writer for failure analysis."""

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import httpx

from src.ingest.fetch_pipeline import FetchOutcome
from src.config import settings

logger = logging.getLogger(__name__)


class DebugBundleWriter:
    """
    Writes debug bundles for failure outcomes.
    
    Bundles include:
    - HTTP headers
    - Response metadata
    - HTML content
    - Screenshots (if browser)
    - Metadata about the fetch attempt
    """
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize debug bundle writer.
        
        Args:
            base_path: Base path for bundle storage (defaults to config)
        """
        self.base_path = Path(base_path or getattr(settings, 'debug_bundle_path', 'data/debug_bundles'))
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_bundle_dir(
        self,
        outcome: FetchOutcome,
        store: str,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        """
        Get bundle directory path.
        
        Args:
            outcome: Fetch outcome
            store: Store identifier
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            Bundle directory path
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")
        bundle_name = f"{timestamp_str}_{outcome.value}"
        
        return self.base_path / store / bundle_name
    
    async def write_bundle(
        self,
        outcome: FetchOutcome,
        store: str,
        url: str,
        html: Optional[str] = None,
        response: Optional[httpx.Response] = None,
        screenshot: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Write debug bundle for HTTP fetch failure.
        
        Args:
            outcome: Fetch outcome
            store: Store identifier
            url: Requested URL
            html: Optional HTML content
            response: Optional HTTP response
            screenshot: Optional screenshot bytes
            metadata: Optional additional metadata
            
        Returns:
            Path to bundle directory
        """
        bundle_dir = self._get_bundle_dir(outcome, store)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        
        # Write headers
        headers_data = {}
        if response:
            headers_data = {
                "request_headers": dict(response.request.headers),
                "response_headers": dict(response.headers),
                "status_code": response.status_code,
                "status_phrase": response.reason_phrase,
                "final_url": str(response.url),
            }
        
        headers_path = bundle_dir / "headers.json"
        with open(headers_path, "w") as f:
            json.dump(headers_data, f, indent=2, default=str)
        
        # Write response metadata
        response_data = {}
        if response:
            response_data = {
                "url": url,
                "final_url": str(response.url),
                "status_code": response.status_code,
                "status_phrase": response.reason_phrase,
                "elapsed": response.elapsed.total_seconds() if response.elapsed else None,
                "http_version": response.http_version,
                "content_length": len(response.content) if response.content else 0,
                "content_type": response.headers.get("Content-Type"),
            }
        
        response_path = bundle_dir / "response.json"
        with open(response_path, "w") as f:
            json.dump(response_data, f, indent=2, default=str)
        
        # Write HTML content
        if html:
            html_path = bundle_dir / "html.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
        
        # Write screenshot if available
        if screenshot:
            screenshot_path = bundle_dir / "screenshot.png"
            with open(screenshot_path, "wb") as f:
                f.write(screenshot)
        
        # Write metadata
        metadata_dict = {
            "outcome": outcome.value,
            "store": store,
            "url": url,
            "timestamp": datetime.utcnow().isoformat(),
            **(metadata or {}),
        }
        
        metadata_path = bundle_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata_dict, f, indent=2, default=str)
        
        logger.info(f"Wrote debug bundle to {bundle_dir}")
        return bundle_dir
    
    async def write_browser_bundle(
        self,
        outcome: FetchOutcome,
        store: str,
        url: str,
        page_content: str,
        screenshot: bytes,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Write debug bundle for browser fetch failure.
        
        Args:
            outcome: Fetch outcome
            store: Store identifier
            url: Requested URL
            page_content: Page HTML content
            screenshot: Screenshot bytes
            metadata: Optional additional metadata
            
        Returns:
            Path to bundle directory
        """
        bundle_dir = self._get_bundle_dir(outcome, store)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        
        # Write HTML content
        html_path = bundle_dir / "html.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page_content)
        
        # Write screenshot
        screenshot_path = bundle_dir / "screenshot.png"
        with open(screenshot_path, "wb") as f:
            f.write(screenshot)
        
        # Write metadata
        metadata_dict = {
            "outcome": outcome.value,
            "store": store,
            "url": url,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "browser",
            **(metadata or {}),
        }
        
        metadata_path = bundle_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata_dict, f, indent=2, default=str)
        
        logger.info(f"Wrote browser debug bundle to {bundle_dir}")
        return bundle_dir


# Global debug bundle writer instance
debug_bundle_writer = DebugBundleWriter()
