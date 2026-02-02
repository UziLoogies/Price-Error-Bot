"""BrickSeek signal source (Walmart/Target/Home Depot/Lowe's)."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class BrickSeekSignalSource(SignalSourceBase):
    tool_name = "brickseek"
    supported_retailers = ["walmart", "target", "homedepot", "lowes"]
