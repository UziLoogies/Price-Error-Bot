"""Candidate processor for signal-driven scanning."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src import metrics
from src.db.models import Candidate, ScanEvidence
from src.detect.baseline import baseline_calculator
from src.detect.engine import DetectionEngine, DetectionResult
from src.detect.deal_detector import DetectedDeal
from src.ingest.candidate_queue import CandidateQueueManager
from src.ingest.escalation_manager import EscalationManager
from src.ingest.product_id_mapper import product_id_mapper
from src.ingest.residential_budget import ResidentialBudgetManager
from src.ingest.registry import FetcherRegistry
from src.normalize.processor import PriceNormalizer, NormalizedPrice
from src.ingest.category_scanner import DiscoveredProduct

logger = logging.getLogger(__name__)


@dataclass
class CandidateProcessResult:
    """Result of processing a candidate."""

    candidate: Candidate
    normalized_price: Optional[NormalizedPrice]
    detection_result: Optional[DetectionResult]
    deal: Optional[DetectedDeal]
    verified: bool
    error: Optional[str] = None


class CandidateProcessor:
    """Process candidates with two-pass scanning and escalation."""

    def __init__(
        self,
        queue_manager: Optional[CandidateQueueManager] = None,
        escalation_manager: Optional[EscalationManager] = None,
        residential_budget: Optional[ResidentialBudgetManager] = None,
    ):
        self._queue_manager = queue_manager or CandidateQueueManager()
        self._escalation = escalation_manager or EscalationManager()
        self._residential_budget = residential_budget or ResidentialBudgetManager()
        self._normalizer = PriceNormalizer()

    async def process_next(
        self,
        db: AsyncSession,
        limit: int = 5,
    ) -> list[CandidateProcessResult]:
        """Process next batch of candidates."""
        candidates = await self._queue_manager.get_next_candidates(db, limit=limit)
        results: list[CandidateProcessResult] = []

        for candidate in candidates:
            result = await self.process_candidate(db, candidate)
            results.append(result)

        return results

    async def process_candidate(
        self,
        db: AsyncSession,
        candidate: Candidate,
    ) -> CandidateProcessResult:
        """Process a single candidate with datacenter then optional residential pass."""
        await db.refresh(candidate)
        candidate.status = "scanning_datacenter"
        await db.commit()

        datacenter_result = await self._scan_candidate(
            db, candidate, proxy_type=settings.datacenter_proxy_pool, scan_pass="datacenter"
        )

        if datacenter_result.error:
            should_escalate = self._escalation.should_escalate(
                error=datacenter_result.error,
                candidate=candidate,
                detection=None,
                normalized_price=None,
            )
        else:
            should_escalate = self._escalation.should_escalate(
                error=None,
                candidate=candidate,
                detection=datacenter_result.detection_result,
                normalized_price=datacenter_result.normalized_price,
            )

        if should_escalate:
            trigger = "error" if datacenter_result.error else "confidence"
            metrics.record_escalation(trigger)
            if not datacenter_result.error:
                candidate.escalation_reason = "high_score"
            if not self._residential_budget.allow_request(candidate.retailer):
                candidate.status = "pending"
                candidate.escalation_reason = "residential_budget_exhausted"
                await db.commit()
                return CandidateProcessResult(
                    candidate=candidate,
                    normalized_price=datacenter_result.normalized_price,
                    detection_result=datacenter_result.detection_result,
                    deal=datacenter_result.deal,
                    verified=False,
                    error="residential_budget_exhausted",
                )

            candidate.status = "scanning_residential"
            await db.commit()
            metrics.record_residential_request(candidate.retailer)
            residential_result = await self._scan_candidate(
                db, candidate, proxy_type=settings.residential_proxy_pool, scan_pass="residential"
            )

            final_result = residential_result if residential_result.normalized_price else datacenter_result
        else:
            final_result = datacenter_result

        # Update candidate status based on detection result
        if final_result.detection_result and final_result.detection_result.triggered:
            candidate.status = "verified"
            candidate.processed_at = datetime.utcnow()
            metrics.record_verified_deal(
                candidate.retailer,
                final_result.detection_result.baseline_source,
            )
        else:
            candidate.status = "rejected"
            candidate.processed_at = datetime.utcnow()

        await db.commit()

        # Record baseline after final decision
        if final_result.normalized_price:
            await self._record_baseline(db, candidate, final_result.normalized_price)

        return CandidateProcessResult(
            candidate=candidate,
            normalized_price=final_result.normalized_price,
            detection_result=final_result.detection_result,
            deal=final_result.deal,
            verified=bool(final_result.detection_result and final_result.detection_result.triggered),
            error=final_result.error,
        )

    async def _scan_candidate(
        self,
        db: AsyncSession,
        candidate: Candidate,
        proxy_type: str,
        scan_pass: str,
    ) -> CandidateProcessResult:
        """Run a single scan pass for a candidate."""
        try:
            retailer, raw_id = product_id_mapper.split_canonical_id(candidate.product_id)
            identifier = raw_id or candidate.product_id
            fetcher = FetcherRegistry.get_fetcher(candidate.retailer)

            raw_price = await fetcher.fetch(identifier, proxy_type=proxy_type)
            normalized = self._normalizer.normalize(raw_price)

            await self._record_evidence(
                db=db,
                candidate=candidate,
                normalized=normalized,
                scan_pass=scan_pass,
                proxy_type=proxy_type,
            )

            product = await baseline_calculator.get_or_create_product(
                db,
                store=candidate.retailer,
                sku=normalized.sku,
                url=normalized.url,
                title=normalized.title,
                msrp=normalized.msrp,
            )

            detection_engine = DetectionEngine(db)
            await db.refresh(candidate, ["source_signal"])
            signal_metadata = (
                candidate.source_signal.metadata_json
                if candidate.source_signal and candidate.source_signal.metadata_json
                else {}
            )
            context = {
                "signal_type": candidate.source_signal.signal_type if candidate.source_signal else None,
                "signal_metadata": signal_metadata,
                "scan_pass": scan_pass,
                "proxy_type": proxy_type,
                **signal_metadata,
            }
            detection_result = await detection_engine.detect(
                product, normalized, context=context
            )

            deal = None
            if detection_result.triggered:
                deal = self._build_deal(
                    candidate,
                    normalized,
                    detection_result,
                    scan_pass=scan_pass,
                    proxy_type=proxy_type,
                )

            return CandidateProcessResult(
                candidate=candidate,
                normalized_price=normalized,
                detection_result=detection_result,
                deal=deal,
                verified=detection_result.triggered,
            )

        except Exception as exc:
            await self._record_evidence(
                db=db,
                candidate=candidate,
                normalized=None,
                scan_pass=scan_pass,
                proxy_type=proxy_type,
                error=str(exc),
            )
            logger.warning("Candidate scan failed (%s): %s", candidate.id, exc)
            return CandidateProcessResult(
                candidate=candidate,
                normalized_price=None,
                detection_result=None,
                deal=None,
                verified=False,
                error=str(exc),
            )

    async def _record_evidence(
        self,
        db: AsyncSession,
        candidate: Candidate,
        normalized: Optional[NormalizedPrice],
        scan_pass: str,
        proxy_type: Optional[str],
        error: Optional[str] = None,
    ) -> None:
        """Persist scan evidence for a pass."""
        if error:
            candidate.escalation_reason = error[:255]
        evidence = ScanEvidence(
            candidate_id=candidate.id,
            scan_pass=scan_pass,
            proxy_type=proxy_type,
            price_confirmed=bool(normalized and normalized.current_price),
            stock_status=normalized.availability if normalized else None,
            observed_price=normalized.current_price if normalized else None,
            timestamp=datetime.utcnow(),
        )
        db.add(evidence)
        await db.commit()

    async def _record_baseline(
        self,
        db: AsyncSession,
        candidate: Candidate,
        normalized: NormalizedPrice,
    ) -> None:
        """Record price history after processing."""
        await baseline_calculator.update_baseline(
            db,
            product_id=(
                await baseline_calculator.get_or_create_product(
                    db,
                    store=candidate.retailer,
                    sku=normalized.sku,
                    url=normalized.url,
                    title=normalized.title,
                    msrp=normalized.msrp,
                )
            ).id,
            new_price=normalized.current_price,
            original_price=normalized.msrp,
        )

    def _build_deal(
        self,
        candidate: Candidate,
        normalized: NormalizedPrice,
        detection_result: DetectionResult,
        scan_pass: str,
        proxy_type: Optional[str],
    ) -> DetectedDeal:
        """Create DetectedDeal from normalized price and detection result."""
        product = DiscoveredProduct(
            sku=normalized.sku,
            title=normalized.title or candidate.product_id,
            url=normalized.url,
            current_price=normalized.current_price,
            original_price=normalized.msrp,
            msrp=normalized.msrp,
            store=candidate.retailer,
        )

        discount_percent = detection_result.discount_percent or 0.0
        if not discount_percent and product.original_price and product.current_price:
            discount_percent = float(
                (1 - product.current_price / product.original_price) * 100
            )

        detection_signals = []
        if candidate.source_signal_id:
            detection_signals.append("signal")
            if candidate.source_signal and candidate.source_signal.signal_type:
                detection_signals.append(candidate.source_signal.signal_type)
        detection_signals.append(
            "two_pass" if candidate.status == "scanning_residential" else "datacenter_pass"
        )

        sold_median = None
        if candidate.source_signal and candidate.source_signal.metadata_json:
            sold_median = candidate.source_signal.metadata_json.get("sold_median_price")

        return DetectedDeal(
            product=product,
            discount_percent=discount_percent,
            detection_method="signal",
            confidence=detection_result.confidence,
            reason=detection_result.reason or "Signal verification",
            category=None,
            detection_signals=detection_signals,
            baseline_price=detection_result.baseline_price,
            baseline_source=detection_result.baseline_source,
            baseline_30d_median=detection_result.baseline_30d_median,
            baseline_90d_median=detection_result.baseline_90d_median,
            verification_details={
                "scan_pass": scan_pass,
                "proxy_type": proxy_type,
                "requirements": detection_result.evidence_requirements,
                "sold_median_price": sold_median,
            },
        )
