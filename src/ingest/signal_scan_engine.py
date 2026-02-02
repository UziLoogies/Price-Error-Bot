"""Signal-driven scan engine orchestrating signal -> candidate -> detect -> alert."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from src.db.session import AsyncSessionLocal
from src.ingest.candidate_processor import CandidateProcessor
from src.ingest.signals.ingestor import signal_ingestor, SignalIngestor
from src.notify.webhook_manager import webhook_manager
from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SignalScanSummary:
    """Summary of a signal scan run."""

    signals_ingested: int = 0
    candidates_created: int = 0
    candidates_processed: int = 0
    verified_deals: int = 0
    errors: List[str] = field(default_factory=list)


class SignalScanEngine:
    """Signal-driven scanning workflow."""

    def __init__(
        self,
        ingestor: SignalIngestor | None = None,
        processor: CandidateProcessor | None = None,
    ):
        self._ingestor = ingestor or signal_ingestor
        self._processor = processor or CandidateProcessor()

    async def run_once(self) -> SignalScanSummary:
        """Run a single signal ingestion + candidate processing loop."""
        summary = SignalScanSummary()
        batch_limit = getattr(settings, "signal_candidate_batch_size", 20)

        async with AsyncSessionLocal() as db:
            try:
                signals, candidate_ids = await self._ingestor.ingest(db)
                summary.signals_ingested = len(signals)
                summary.candidates_created = len(candidate_ids)
            except Exception as exc:
                logger.warning("Signal ingestion failed: %s", exc)
                summary.errors.append(str(exc))
                return summary

            try:
                results = await self._processor.process_next(db, limit=batch_limit)
                summary.candidates_processed = len(results)
                for result in results:
                    if result.deal and result.deal.is_significant:
                        await webhook_manager.send_alert(db, result.deal)
                        summary.verified_deals += 1
            except Exception as exc:
                logger.warning("Candidate processing failed: %s", exc)
                summary.errors.append(str(exc))

        return summary


# Global signal scan engine instance
signal_scan_engine = SignalScanEngine()
