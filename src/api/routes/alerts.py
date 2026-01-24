"""Alert history routes."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import Alert, Product

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: int
    product_id: int
    rule_id: int
    triggered_price: float
    previous_price: float | None
    discord_message_id: str | None
    sent_at: datetime
    product_sku: str | None = None
    product_title: str | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    limit: int = 50, db: AsyncSession = Depends(get_database)
):
    """List recent alerts."""
    result = await db.execute(
        select(Alert, Product.sku, Product.title)
        .join(Product, Alert.product_id == Product.id)
        .order_by(Alert.sent_at.desc())
        .limit(limit)
    )

    alerts = []
    for alert, sku, title in result.all():
        alert_dict = {
            "id": alert.id,
            "product_id": alert.product_id,
            "rule_id": alert.rule_id,
            "triggered_price": float(alert.triggered_price),
            "previous_price": float(alert.previous_price) if alert.previous_price else None,
            "discord_message_id": alert.discord_message_id,
            "sent_at": alert.sent_at,
            "product_sku": sku,
            "product_title": title,
        }
        alerts.append(AlertResponse(**alert_dict))

    return alerts
