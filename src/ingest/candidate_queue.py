"""Candidate queue manager for signal-driven scanning."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Candidate, Signal

logger = logging.getLogger(__name__)


ACTIVE_STATUSES = {"pending", "scanning_datacenter", "scanning_residential"}


class CandidateQueueManager:
    """Manages candidate queue creation and retrieval."""

    async def enqueue_signal(
        self,
        db: AsyncSession,
        signal: Signal,
    ) -> Optional[Candidate]:
        """Create a candidate from a signal if not duplicate and within budget."""
        if not signal.product_id:
            return None

        if await self._exceeds_budget(db, signal.retailer):
            logger.debug("Candidate budget exceeded for %s", signal.retailer)
            return None

        if await self._is_duplicate(db, signal):
            return None

        priority_score = self._calculate_priority(signal)
        candidate = Candidate(
            retailer=signal.retailer,
            product_id=signal.product_id,
            url=signal.url,
            source_signal_id=signal.id,
            priority_score=priority_score,
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.add(candidate)
        await db.flush()
        return candidate

    async def get_next_candidates(
        self,
        db: AsyncSession,
        limit: int = 10,
    ) -> list[Candidate]:
        """Fetch next candidates by priority."""
        query = (
            select(Candidate)
            .where(Candidate.status == "pending")
            .order_by(Candidate.priority_score.desc(), Candidate.created_at.asc())
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def _is_duplicate(self, db: AsyncSession, signal: Signal) -> bool:
        """Check for an existing candidate with same product and price bucket."""
        query = select(Candidate).where(
            Candidate.retailer == signal.retailer,
            Candidate.product_id == signal.product_id,
            Candidate.status.in_(ACTIVE_STATUSES),
        )

        if signal.detected_price is not None:
            query = query.join(Signal, Candidate.source_signal_id == Signal.id).where(
                Signal.detected_price.is_not(None),
                func.abs(Signal.detected_price - signal.detected_price) <= 1,
            )

        result = await db.execute(query)
        return result.scalar_one_or_none() is not None

    async def _exceeds_budget(self, db: AsyncSession, retailer: str) -> bool:
        """Check hourly candidate budget per retailer."""
        limit = getattr(settings, "signal_candidate_max_per_retailer_per_hour", 0)
        if not limit or limit <= 0:
            return False

        cutoff = datetime.utcnow() - timedelta(hours=1)
        query = select(func.count(Candidate.id)).where(
            Candidate.retailer == retailer,
            Candidate.created_at >= cutoff,
        )
        result = await db.execute(query)
        count = result.scalar() or 0
        return count >= limit

    def _calculate_priority(self, signal: Signal) -> float:
        """Score candidate priority based on signal metadata and price."""
        score = 0.0
        price = signal.detected_price
        metadata = signal.metadata_json or {}

        # Penny deals
        if price is not None and price <= Decimal("1.00"):
            score += 10.0

        # Discount percentage (if metadata provides baseline/msrp)
        discount_percent = self._infer_discount_percent(price, metadata)
        if discount_percent is not None:
            if discount_percent >= 70:
                score += 8.0
            elif discount_percent >= 50:
                score += 5.0

        # Fast movers
        if metadata.get("price_change_count_24h", 0) >= 2:
            score += 5.0

        # High-ticket items
        if price is not None and price >= Decimal("200"):
            score += 3.0

        # Small boost for high-signal types
        signal_type = (signal.signal_type or "").lower()
        if signal_type in {"new_low", "clearance"}:
            score += 2.0

        return score

    @staticmethod
    def _infer_discount_percent(
        price: Optional[Decimal],
        metadata: dict,
    ) -> Optional[float]:
        """Infer discount percent using metadata."""
        if price is None:
            return None
        baseline = metadata.get("baseline_price") or metadata.get("msrp")
        try:
            if baseline and baseline > 0:
                return float((1 - (price / Decimal(str(baseline)))) * 100)
        except Exception:
            return None
        return None
