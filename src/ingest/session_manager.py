"""Session management for persistent cookies and browser profiles."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages persistent cookies and browser profiles per retailer."""

    def __init__(self):
        self.session_dir = Path(settings.session_storage_path)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.cookies: dict[str, list[dict]] = {}

    def _get_cookie_path(self, retailer: str) -> Path:
        """Get path to cookie file for retailer."""
        return self.session_dir / f"{retailer}_cookies.json"

    def _get_profile_path(self, retailer: str) -> Path:
        """Get path to browser profile directory for retailer."""
        return self.session_dir / f"{retailer}_profile"

    def load_cookies(self, retailer: str) -> list[dict]:
        """Load cookies from disk for a retailer."""
        cookie_path = self._get_cookie_path(retailer)

        if retailer in self.cookies:
            return self.cookies[retailer]

        if not cookie_path.exists():
            return []

        try:
            with open(cookie_path, "r") as f:
                cookies = json.load(f)
                self.cookies[retailer] = cookies
                return cookies
        except Exception as e:
            logger.warning(f"Failed to load cookies for {retailer}: {e}")
            return []

    def save_cookies(self, retailer: str, cookies: list[dict]) -> None:
        """Save cookies to disk for a retailer."""
        cookie_path = self._get_cookie_path(retailer)

        try:
            self.cookies[retailer] = cookies
            with open(cookie_path, "w") as f:
                json.dump(cookies, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cookies for {retailer}: {e}")

    def update_cookies_from_response(
        self, retailer: str, response: httpx.Response
    ) -> None:
        """Update cookies from HTTP response."""
        existing = self.load_cookies(retailer)
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

        # Convert back to list
        updated_cookies = list(cookie_dict.values())
        self.save_cookies(retailer, updated_cookies)

    def get_cookie_header(self, retailer: str, domain: str) -> str:
        """Get cookie header string for a retailer and domain."""
        cookies = self.load_cookies(retailer)
        cookie_pairs = []

        for cookie in cookies:
            cookie_domain = cookie.get("domain", "")
            # Match domain (exact or subdomain)
            if cookie_domain == domain or domain.endswith("." + cookie_domain.lstrip(".")):
                cookie_pairs.append(f"{cookie['name']}={cookie['value']}")

        return "; ".join(cookie_pairs)

    def get_playwright_profile_path(self, retailer: str) -> Optional[Path]:
        """Get browser profile path for Playwright (persistent context)."""
        profile_path = self._get_profile_path(retailer)
        profile_path.mkdir(parents=True, exist_ok=True)
        return profile_path

    def clear_session(self, retailer: str) -> None:
        """Clear all session data for a retailer."""
        cookie_path = self._get_cookie_path(retailer)
        profile_path = self._get_profile_path(retailer)

        if retailer in self.cookies:
            del self.cookies[retailer]

        if cookie_path.exists():
            cookie_path.unlink()

        if profile_path.exists():
            import shutil

            shutil.rmtree(profile_path)


# Global session manager instance
session_manager = SessionManager()
