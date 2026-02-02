"""PriceLasso signal source."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class PriceLassoSignalSource(SignalSourceBase):
    tool_name = "pricelasso"
    supported_retailers = [
        "bestbuy",
        "target",
        "macys",
        "microcenter",
        "gamestop",
        "bhphotovideo",
        "officedepot",
    ]
