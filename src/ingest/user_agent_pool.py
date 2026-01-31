"""Large user agent pool with rotation and browser version matching.

Maintains a pool of realistic user agents and ensures consistency
between user agent strings and browser versions.
"""

import logging
import random
from typing import Optional, List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class UserAgentInfo:
    """User agent with metadata."""
    user_agent: str
    browser: str  # 'chrome', 'firefox', 'safari', 'edge'
    version: str
    platform: str  # 'windows', 'mac', 'linux'
    os_version: str


class UserAgentPool:
    """
    Large pool of realistic user agents with rotation.
    
    Features:
    - 1000+ realistic user agents
    - Browser version matching
    - Platform consistency
    - Usage tracking to avoid repetition
    """
    
    def __init__(self, pool_size: int = 1000):
        """
        Initialize user agent pool.
        
        Args:
            pool_size: Target pool size (will generate if needed)
        """
        self.pool_size = pool_size
        self._user_agents: List[UserAgentInfo] = []
        self._usage_tracker: Dict[str, int] = {}  # Track usage count per UA
        self._recent_used: List[str] = []  # Recently used UAs (avoid immediate reuse)
        self._recent_size = 50
        
        self._generate_pool()
    
    def _generate_pool(self):
        """Generate a large pool of realistic user agents."""
        # Chrome on Windows
        chrome_windows = [
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
            for version in range(110, 122)  # Chrome 110-121
        ]
        
        # Chrome on macOS
        chrome_macos = [
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
            for version in range(110, 122)
        ]
        
        # Firefox on Windows
        firefox_windows = [
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
            for version in range(115, 122)
        ]
        
        # Firefox on macOS
        firefox_macos = [
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"
            for version in range(115, 122)
        ]
        
        # Safari on macOS
        safari_macos = [
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{version}.0 Safari/605.1.15"
            for version in range(16, 18)
        ]
        
        # Edge on Windows
        edge_windows = [
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36 Edg/{version}.0.0.0"
            for version in range(110, 122)
        ]
        
        # Combine all
        all_ua_strings = (
            chrome_windows + chrome_macos +
            firefox_windows + firefox_macos +
            safari_macos + edge_windows
        )
        
        # Generate more variations to reach pool size
        while len(all_ua_strings) < self.pool_size:
            # Duplicate and vary
            base = random.choice(all_ua_strings)
            all_ua_strings.append(base)
        
        # Parse into UserAgentInfo objects
        for ua_string in all_ua_strings[:self.pool_size]:
            info = self._parse_user_agent(ua_string)
            if info:
                self._user_agents.append(info)
                self._usage_tracker[ua_string] = 0
        
        logger.info(f"Generated user agent pool with {len(self._user_agents)} agents")
    
    def _parse_user_agent(self, ua_string: str) -> Optional[UserAgentInfo]:
        """Parse user agent string into structured info."""
        import re
        
        # Detect browser
        if "Chrome" in ua_string and "Edg" in ua_string:
            browser = "edge"
        elif "Chrome" in ua_string:
            browser = "chrome"
        elif "Firefox" in ua_string:
            browser = "firefox"
        elif "Safari" in ua_string and "Chrome" not in ua_string:
            browser = "safari"
        else:
            browser = "chrome"  # Default
        
        # Detect platform
        if "Windows" in ua_string:
            platform = "windows"
            os_version = "10.0"
        elif "Macintosh" in ua_string:
            platform = "mac"
            os_version = "10_15_7"
        elif "Linux" in ua_string:
            platform = "linux"
            os_version = ""
        else:
            platform = "windows"
            os_version = "10.0"
        
        # Extract version
        version_match = re.search(r'(?:Chrome|Firefox|Safari|Edg)/(\d+)', ua_string)
        version = version_match.group(1) if version_match else "120"
        
        return UserAgentInfo(
            user_agent=ua_string,
            browser=browser,
            version=version,
            platform=platform,
            os_version=os_version,
        )
    
    def get_random(self, exclude_recent: bool = True) -> str:
        """
        Get a random user agent from the pool.
        
        Args:
            exclude_recent: Exclude recently used user agents
            
        Returns:
            User agent string
        """
        available = self._user_agents
        
        if exclude_recent and self._recent_used:
            available = [
                ua for ua in self._user_agents
                if ua.user_agent not in self._recent_used
            ]
            if not available:
                available = self._user_agents  # Fallback if all are recent
        
        selected = random.choice(available)
        
        # Track usage
        self._usage_tracker[selected.user_agent] = self._usage_tracker.get(selected.user_agent, 0) + 1
        
        # Add to recent list
        self._recent_used.append(selected.user_agent)
        if len(self._recent_used) > self._recent_size:
            self._recent_used.pop(0)
        
        return selected.user_agent
    
    def get_for_browser(self, browser: str, platform: Optional[str] = None) -> str:
        """
        Get user agent for specific browser and platform.
        
        Args:
            browser: Browser type ('chrome', 'firefox', 'safari', 'edge')
            platform: Platform ('windows', 'mac', 'linux')
            
        Returns:
            User agent string
        """
        available = [
            ua for ua in self._user_agents
            if ua.browser == browser and (platform is None or ua.platform == platform)
        ]
        
        if not available:
            # Fallback to any user agent
            return self.get_random()
        
        selected = random.choice(available)
        self._usage_tracker[selected.user_agent] = self._usage_tracker.get(selected.user_agent, 0) + 1
        
        return selected.user_agent
    
    def get_matching(self, browser_version: str, platform: Optional[str] = None) -> str:
        """
        Get user agent matching specific browser version.
        
        Args:
            browser_version: Browser version (e.g., '120')
            platform: Platform ('windows', 'mac', 'linux')
            
        Returns:
            User agent string
        """
        available = [
            ua for ua in self._user_agents
            if ua.version == browser_version and (platform is None or ua.platform == platform)
        ]
        
        if not available:
            return self.get_random()
        
        selected = random.choice(available)
        self._usage_tracker[selected.user_agent] = self._usage_tracker.get(selected.user_agent, 0) + 1
        
        return selected.user_agent
    
    def get_stats(self) -> Dict[str, any]:
        """Get pool statistics."""
        return {
            "total_agents": len(self._user_agents),
            "browser_distribution": self._get_browser_distribution(),
            "platform_distribution": self._get_platform_distribution(),
            "most_used": sorted(
                self._usage_tracker.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
        }
    
    def _get_browser_distribution(self) -> Dict[str, int]:
        """Get distribution of browsers in pool."""
        dist = {}
        for ua in self._user_agents:
            dist[ua.browser] = dist.get(ua.browser, 0) + 1
        return dist
    
    def _get_platform_distribution(self) -> Dict[str, int]:
        """Get distribution of platforms in pool."""
        dist = {}
        for ua in self._user_agents:
            dist[ua.platform] = dist.get(ua.platform, 0) + 1
        return dist


# Global user agent pool instance
user_agent_pool = UserAgentPool(pool_size=getattr(settings, 'user_agent_pool_size', 1000))
