"""Base classes for third-party signal sources."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SignalPayload:
    """In-memory signal payload from a source."""

    retailer: str
    product_id: str
    url: Optional[str]
    detected_price: Optional[Decimal]
    detected_at: datetime
    signal_type: str
    source_tool: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SignalSourceBase:
    """Base class for signal source implementations."""

    tool_name: str = "unknown"
    supported_retailers: List[str] = []

    async def fetch_signals(
        self,
        retailer: str,
        config: Optional[dict] = None,
    ) -> List[SignalPayload]:
        """
        Fetch signals for a retailer.

        Implementations should return a list of SignalPayload objects.
        """
        config = config or {}
        mock_signals = config.get("mock_signals") or []
        if mock_signals:
            return self._build_mock_signals(retailer, mock_signals)
        logger.debug("No signal fetch implemented for %s (%s)", self.tool_name, retailer)
        return []

    def supports(self, retailer: str) -> bool:
        """Check if the source supports a retailer."""
        return retailer in self.supported_retailers

    def _build_mock_signals(
        self,
        retailer: str,
        mock_signals: List[dict],
    ) -> List[SignalPayload]:
        """Build signals from mock config entries."""
        signals: List[SignalPayload] = []
        for item in mock_signals:
            try:
                price = item.get("detected_price")
                if price is not None and not isinstance(price, Decimal):
                    price = Decimal(str(price))
                signals.append(
                    SignalPayload(
                        retailer=retailer,
                        product_id=str(item.get("product_id") or ""),
                        url=item.get("url"),
                        detected_price=price,
                        detected_at=item.get("detected_at") or datetime.utcnow(),
                        signal_type=item.get("signal_type") or "price_drop",
                        source_tool=self.tool_name,
                        metadata=item.get("metadata") or {},
                    )
                )
            except Exception as exc:
                logger.debug("Failed to build mock signal: %s", exc)
        return signals
