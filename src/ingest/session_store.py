"""Proxy-specific session persistence across restarts."""

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    """Metadata for a proxy session."""
    
    store: str
    proxy_id: int
    user_agent: str
    session_key: str
    last_used: datetime
    success_count: int = 0
    fail_count: int = 0
    last_blocked_at: Optional[datetime] = None
    last_http_status: Optional[int] = None
    created_at: datetime = None
    
    def __post_init__(self):
        """Set created_at if not provided."""
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class SessionStore:
    """
    Manages proxy-specific session persistence.
    
    Features:
    - Per-session cookie storage
    - Playwright storage state persistence
    - Session metadata tracking
    - LRU eviction for old sessions
    """
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize session store.
        
        Args:
            base_path: Base path for session storage (defaults to config)
        """
        self.base_path = Path(base_path or getattr(settings, 'session_storage_path', 'data/sessions'))
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._metadata_cache: Dict[str, SessionMetadata] = {}
    
    def _generate_session_key(
        self,
        store: str,
        proxy_id: int,
        user_agent: str,
    ) -> str:
        """
        Generate stable session key from store, proxy, and user agent.
        
        Args:
            store: Store identifier
            proxy_id: Proxy ID
            user_agent: User agent string
            
        Returns:
            Session key string
        """
        # Hash user agent for shorter key
        ua_hash = hashlib.md5(user_agent.encode()).hexdigest()[:8]
        return f"{store}_{proxy_id}_{ua_hash}"
    
    def get_session_key(
        self,
        store: str,
        proxy_id: int,
        user_agent: str,
    ) -> str:
        """
        Get or generate session key.
        
        Args:
            store: Store identifier
            proxy_id: Proxy ID
            user_agent: User agent string
            
        Returns:
            Session key
        """
        return self._generate_session_key(store, proxy_id, user_agent)
    
    def _get_session_dir(self, store: str, session_key: str) -> Path:
        """Get session directory path."""
        return self.base_path / store / session_key
    
    def _get_cookie_path(self, store: str, session_key: str) -> Path:
        """Get cookie file path."""
        return self._get_session_dir(store, session_key) / "cookies.json"
    
    def _get_storage_state_path(self, store: str, session_key: str) -> Path:
        """Get Playwright storage state path."""
        return self._get_session_dir(store, session_key) / "storage_state.json"
    
    def _get_metadata_path(self, store: str, session_key: str) -> Path:
        """Get metadata file path."""
        return self._get_session_dir(store, session_key) / "metadata.json"
    
    def _get_profile_path(self, store: str, session_key: str) -> Path:
        """Get Playwright profile directory path."""
        return self._get_session_dir(store, session_key) / "profile"
    
    def load_cookies(
        self,
        store: str,
        session_key: str,
    ) -> List[Dict[str, Any]]:
        """
        Load cookies for a session.
        
        Args:
            store: Store identifier
            session_key: Session key
            
        Returns:
            List of cookie dictionaries
        """
        cookie_path = self._get_cookie_path(store, session_key)
        
        if not cookie_path.exists():
            return []
        
        try:
            with open(cookie_path, "r") as f:
                cookies = json.load(f)
                return cookies if isinstance(cookies, list) else []
        except Exception as e:
            logger.warning(f"Failed to load cookies for {store}/{session_key}: {e}")
            return []
    
    def save_cookies(
        self,
        store: str,
        session_key: str,
        cookies: List[Dict[str, Any]],
    ) -> None:
        """
        Save cookies for a session.
        
        Args:
            store: Store identifier
            session_key: Session key
            cookies: List of cookie dictionaries
        """
        cookie_path = self._get_cookie_path(store, session_key)
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(cookie_path, "w") as f:
                json.dump(cookies, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save cookies for {store}/{session_key}: {e}")
    
    def update_cookies_from_response(
        self,
        store: str,
        session_key: str,
        response: httpx.Response,
    ) -> None:
        """
        Update cookies from HTTP response.
        
        Args:
            store: Store identifier
            session_key: Session key
            response: HTTP response
        """
        existing = self.load_cookies(store, session_key)
        cookie_dict = {}
        
        # Convert existing list to dict
        for cookie in existing:
            cookie_dict[cookie["name"]] = cookie
        
        # Update with new cookies from response
        for cookie in response.cookies.jar:
            cookie_dict[cookie.name] = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path or "/",
            }
        
        # Convert back to list and save
        updated_cookies = list(cookie_dict.values())
        self.save_cookies(store, session_key, updated_cookies)
    
    def load_storage_state(
        self,
        store: str,
        session_key: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Load Playwright storage state.
        
        Args:
            store: Store identifier
            session_key: Session key
            
        Returns:
            Storage state dictionary or None
        """
        state_path = self._get_storage_state_path(store, session_key)
        
        if not state_path.exists():
            return None
        
        try:
            with open(state_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load storage state for {store}/{session_key}: {e}")
            return None
    
    def save_storage_state(
        self,
        store: str,
        session_key: str,
        state: Dict[str, Any],
    ) -> None:
        """
        Save Playwright storage state.
        
        Args:
            store: Store identifier
            session_key: Session key
            state: Storage state dictionary
        """
        state_path = self._get_storage_state_path(store, session_key)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save storage state for {store}/{session_key}: {e}")
    
    def get_profile_path(
        self,
        store: str,
        session_key: str,
    ) -> Path:
        """
        Get Playwright profile directory path.
        
        Args:
            store: Store identifier
            session_key: Session key
            
        Returns:
            Profile directory path
        """
        profile_path = self._get_profile_path(store, session_key)
        profile_path.mkdir(parents=True, exist_ok=True)
        return profile_path
    
    def load_metadata(
        self,
        store: str,
        session_key: str,
    ) -> Optional[SessionMetadata]:
        """
        Load session metadata.
        
        Args:
            store: Store identifier
            session_key: Session key
            
        Returns:
            SessionMetadata or None
        """
        # Check cache first
        cache_key = f"{store}:{session_key}"
        if cache_key in self._metadata_cache:
            return self._metadata_cache[cache_key]
        
        metadata_path = self._get_metadata_path(store, session_key)
        
        if not metadata_path.exists():
            return None
        
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
                # Convert datetime strings back to datetime objects
                for date_field in ["last_used", "last_blocked_at", "created_at"]:
                    if date_field in data and data[date_field]:
                        data[date_field] = datetime.fromisoformat(data[date_field])
                
                metadata = SessionMetadata(**data)
                self._metadata_cache[cache_key] = metadata
                return metadata
        except Exception as e:
            logger.warning(f"Failed to load metadata for {store}/{session_key}: {e}")
            return None
    
    def save_metadata(
        self,
        metadata: SessionMetadata,
    ) -> None:
        """
        Save session metadata.
        
        Args:
            metadata: SessionMetadata instance
        """
        metadata_path = self._get_metadata_path(metadata.store, metadata.session_key)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Update cache
        cache_key = f"{metadata.store}:{metadata.session_key}"
        self._metadata_cache[cache_key] = metadata
        
        try:
            # Convert to dict with datetime serialization
            data = asdict(metadata)
            for date_field in ["last_used", "last_blocked_at", "created_at"]:
                if data.get(date_field):
                    data[date_field] = data[date_field].isoformat()
            
            with open(metadata_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save metadata for {metadata.store}/{metadata.session_key}: {e}")
    
    def update_metadata(
        self,
        store: str,
        session_key: str,
        proxy_id: int,
        user_agent: str,
        success: bool = True,
        http_status: Optional[int] = None,
    ) -> SessionMetadata:
        """
        Update session metadata with usage information.
        
        Args:
            store: Store identifier
            session_key: Session key
            proxy_id: Proxy ID
            user_agent: User agent string
            success: Whether request succeeded
            http_status: HTTP status code
            
        Returns:
            Updated SessionMetadata
        """
        metadata = self.load_metadata(store, session_key)
        
        if metadata is None:
            metadata = SessionMetadata(
                store=store,
                proxy_id=proxy_id,
                user_agent=user_agent,
                session_key=session_key,
                last_used=datetime.utcnow(),
            )
        
        metadata.last_used = datetime.utcnow()
        metadata.last_http_status = http_status
        
        if success:
            metadata.success_count += 1
        else:
            metadata.fail_count += 1
            if http_status in (401, 403):
                metadata.last_blocked_at = datetime.utcnow()
        
        self.save_metadata(metadata)
        return metadata
    
    def clear_session(
        self,
        store: str,
        session_key: str,
    ) -> None:
        """
        Clear all session data.
        
        Args:
            store: Store identifier
            session_key: Session key
        """
        session_dir = self._get_session_dir(store, session_key)
        
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
        
        # Remove from cache
        cache_key = f"{store}:{session_key}"
        if cache_key in self._metadata_cache:
            del self._metadata_cache[cache_key]
    
    def get_cookie_header(
        self,
        store: str,
        session_key: str,
        domain: str,
    ) -> str:
        """
        Get cookie header string for a session and domain.
        
        Args:
            store: Store identifier
            session_key: Session key
            domain: Target domain
            
        Returns:
            Cookie header string
        """
        cookies = self.load_cookies(store, session_key)
        cookie_pairs = []
        
        for cookie in cookies:
            cookie_domain = cookie.get("domain", "")
            # Match domain (exact or subdomain)
            if cookie_domain == domain or domain.endswith("." + cookie_domain.lstrip(".")):
                cookie_pairs.append(f"{cookie['name']}={cookie['value']}")
        
        return "; ".join(cookie_pairs)


# Global session store instance
session_store = SessionStore()
