"""Residential proxy budget manager."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from threading import Lock
from typing import Deque, Dict

from src.config import settings

logger = logging.getLogger(__name__)


class ResidentialBudgetManager:
    """Tracks residential proxy usage and enforces hourly/daily limits."""

    def __init__(
        self,
        max_per_hour: int | None = None,
        max_per_day: int | None = None,
    ):
        self._max_per_hour = max_per_hour or settings.max_residential_requests_per_hour
        self._max_per_day = max_per_day or settings.max_residential_requests_per_day
        self._hourly: Dict[str, Deque[datetime]] = {}
        self._daily: Dict[str, Deque[datetime]] = {}
        self._lock = Lock()

    def allow_request(self, key: str) -> bool:
        """Check and record a residential request for a key (retailer/domain)."""
        now = datetime.utcnow()
        with self._lock:
            hourly = self._hourly.setdefault(key, deque())
            daily = self._daily.setdefault(key, deque())

            self._trim_queue(hourly, now - timedelta(hours=1))
            self._trim_queue(daily, now - timedelta(days=1))

            if self._max_per_hour and len(hourly) >= self._max_per_hour:
                return False
            if self._max_per_day and len(daily) >= self._max_per_day:
                return False

            hourly.append(now)
            daily.append(now)
            return True

    @staticmethod
    def _trim_queue(queue: Deque[datetime], cutoff: datetime) -> None:
        """Trim timestamps older than cutoff."""
        while queue and queue[0] < cutoff:
            queue.popleft()
