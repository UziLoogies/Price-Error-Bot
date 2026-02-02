"""Warehouse Runner signal source (Costco)."""

from __future__ import annotations

from src.ingest.signals.sources.base import SignalSourceBase


class WarehouseRunnerSignalSource(SignalSourceBase):
    tool_name = "warehouserunner"
    supported_retailers = ["costco"]
