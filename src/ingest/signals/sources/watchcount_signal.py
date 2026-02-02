"""WatchCount signal source (eBay)."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class WatchCountSignalSource(SignalSourceBase):
    tool_name = "watchcount"
    supported_retailers = ["ebay"]
