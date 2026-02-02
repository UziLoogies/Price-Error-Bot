"""Keepa signal source (Amazon)."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class KeepaSignalSource(SignalSourceBase):
    tool_name = "keepa"
    supported_retailers = ["amazon_us"]
