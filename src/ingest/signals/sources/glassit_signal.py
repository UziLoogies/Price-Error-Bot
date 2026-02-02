"""Glass It signal source."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class GlassItSignalSource(SignalSourceBase):
    tool_name = "glassit"
    supported_retailers = ["newegg", "kohls"]
