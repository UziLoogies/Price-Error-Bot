"""Signal ingestor for third-party price tracking tools."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import SignalSource, Signal
from src.ingest.candidate_queue import CandidateQueueManager
from src.ingest.signals.sources import (
    SignalPayload,
    KeepaSignalSource,
    BrickSeekSignalSource,
    PriceLassoSignalSource,
    GlassItSignalSource,
    WarehouseRunnerSignalSource,
    WatchCountSignalSource,
)
from src.ingest.product_id_mapper import product_id_mapper
from src import metrics

logger = logging.getLogger(__name__)


SOURCE_REGISTRY = {
    "keepa": KeepaSignalSource,
    "brickseek": BrickSeekSignalSource,
    "pricelasso": PriceLassoSignalSource,
    "glassit": GlassItSignalSource,
    "warehouserunner": WarehouseRunnerSignalSource,
    "watchcount": WatchCountSignalSource,
}


class SignalIngestor:
    """Orchestrates signal ingestion from configured sources."""

    def __init__(
        self,
        candidate_queue: Optional[CandidateQueueManager] = None,
    ):
        self._candidate_queue = candidate_queue or CandidateQueueManager()
        self._sources: Dict[str, object] = {}

    def _get_source(self, tool: str):
        """Get or create source instance for a tool."""
        tool = tool.lower()
        if tool not in SOURCE_REGISTRY:
            return None
        if tool not in self._sources:
            self._sources[tool] = SOURCE_REGISTRY[tool]()
        return self._sources[tool]

    async def ingest(self, db: AsyncSession) -> tuple[list[Signal], list[int]]:
        """
        Ingest signals from all enabled sources and enqueue candidates.

        Returns:
            Tuple of (new_signals, candidate_ids)
        """
        if not settings.third_party_enabled:
            logger.debug("Third-party signals disabled")
            return [], []

        payloads = await self._fetch_all_payloads()
        if not payloads:
            return [], []

        new_signals: List[Signal] = []
        candidate_ids: List[int] = []

        for payload in payloads:
            if payload.product_id and ":" not in payload.product_id:
                canonical = product_id_mapper.canonicalize(
                    retailer=payload.retailer,
                    product_id=payload.product_id,
                    url=payload.url,
                )
                payload.product_id = canonical.as_string()
            source_model = await self._get_or_create_source(db, payload)
            if not source_model:
                continue

            if await self._signal_recent_exists(db, payload):
                continue

            signal_model = Signal(
                source_id=source_model.id,
                retailer=payload.retailer,
                product_id=payload.product_id,
                url=payload.url,
                detected_price=payload.detected_price,
                detected_at=payload.detected_at,
                signal_type=payload.signal_type,
                metadata_json=payload.metadata,
                processed=False,
            )
            db.add(signal_model)
            await db.flush()
            new_signals.append(signal_model)
            metrics.record_signal_ingested(payload.source_tool)

            candidate = await self._candidate_queue.enqueue_signal(db, signal_model)
            if candidate:
                signal_model.processed = True
                candidate_ids.append(candidate.id)
                metrics.record_candidate_created(candidate.retailer)

        if new_signals:
            await db.commit()

        return new_signals, candidate_ids

    async def _fetch_all_payloads(self) -> list[SignalPayload]:
        """Fetch signals from configured sources."""
        payloads: List[SignalPayload] = []
        for retailer, config in settings.signal_sources.items():
            if not config or not config.get("enabled"):
                continue
            tool = config.get("tool")
            if not tool:
                continue
            source = self._get_source(tool)
            if not source:
                logger.warning("Unknown signal source tool: %s", tool)
                continue
            try:
                source_payloads = await source.fetch_signals(retailer, config)
                payloads.extend(source_payloads)
            except Exception as exc:
                logger.warning("Signal source %s failed for %s: %s", tool, retailer, exc)
        return self._dedupe_payloads(payloads)

    def _dedupe_payloads(self, payloads: List[SignalPayload]) -> List[SignalPayload]:
        """Deduplicate payloads by retailer + product_id + price bucket."""
        seen = set()
        unique: List[SignalPayload] = []
        for payload in payloads:
            price_bucket = None
            if payload.detected_price is not None:
                price_bucket = int(payload.detected_price)
            key = (payload.retailer, payload.product_id, price_bucket, payload.signal_type)
            if key in seen:
                continue
            seen.add(key)
            unique.append(payload)
        return unique

    async def _get_or_create_source(
        self,
        db: AsyncSession,
        payload: SignalPayload,
    ) -> Optional[SignalSource]:
        """Fetch or create SignalSource record."""
        query = select(SignalSource).where(
            SignalSource.retailer == payload.retailer,
            SignalSource.source_tool == payload.source_tool,
        )
        result = await db.execute(query)
        source = result.scalar_one_or_none()
        if source:
            return source

        source = SignalSource(
            retailer=payload.retailer,
            source_tool=payload.source_tool,
            enabled=True,
        )
        db.add(source)
        await db.flush()
        return source

    async def _signal_recent_exists(
        self,
        db: AsyncSession,
        payload: SignalPayload,
    ) -> bool:
        """Check if a similar signal exists recently."""
        cutoff = datetime.utcnow() - timedelta(hours=settings.dedupe_ttl_hours)
        query = select(Signal).where(
            Signal.retailer == payload.retailer,
            Signal.product_id == payload.product_id,
            Signal.created_at >= cutoff,
        )

        if payload.detected_price is not None:
            query = query.where(
                func.abs(Signal.detected_price - payload.detected_price) <= 1
            )
        if payload.signal_type:
            query = query.where(Signal.signal_type == payload.signal_type)

        result = await db.execute(query)
        return result.scalar_one_or_none() is not None


# Global ingestor instance
signal_ingestor = SignalIngestor()
