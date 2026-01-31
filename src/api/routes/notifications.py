"""API endpoints for webhook configuration and notification management."""

import json
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models import Webhook, NotificationHistory
from src.notify.webhook_manager import webhook_manager, WebhookType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# Pydantic models for API
class WebhookCreate(BaseModel):
    """Request model for creating a webhook."""
    name: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., min_length=1)
    webhook_type: str = Field(default="discord", pattern="^(discord|telegram|slack|generic)$")
    enabled: bool = Field(default=True)
    template: Optional[str] = Field(default=None)
    headers: Optional[str] = Field(default=None, description="JSON string of custom headers")
    filters: Optional[str] = Field(default=None, description="JSON string of filters")
    telegram_chat_id: Optional[str] = Field(default=None)
    telegram_bot_token: Optional[str] = Field(default=None)


class WebhookUpdate(BaseModel):
    """Request model for updating a webhook."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    url: Optional[str] = Field(default=None, min_length=1)
    webhook_type: Optional[str] = Field(default=None, pattern="^(discord|telegram|slack|generic)$")
    enabled: Optional[bool] = Field(default=None)
    template: Optional[str] = Field(default=None)
    headers: Optional[str] = Field(default=None)
    filters: Optional[str] = Field(default=None)
    telegram_chat_id: Optional[str] = Field(default=None)
    telegram_bot_token: Optional[str] = Field(default=None)


class WebhookResponse(BaseModel):
    """Response model for webhook data."""
    id: int
    name: Optional[str]
    url: str
    webhook_type: str
    enabled: bool
    template: Optional[str]
    headers: Optional[str]
    filters: Optional[str]
    telegram_chat_id: Optional[str]
    send_count: int
    error_count: int
    last_sent_at: Optional[datetime]
    created_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class NotificationHistoryResponse(BaseModel):
    """Response model for notification history."""
    id: int
    webhook_id: int
    product_id: Optional[int]
    notification_type: str
    status: str
    payload: Optional[str]
    error_message: Optional[str]
    sent_at: datetime
    response_time_ms: Optional[int]
    
    class Config:
        from_attributes = True


class WebhookTestResult(BaseModel):
    """Response model for webhook test."""
    success: bool
    message: str


class WebhookStats(BaseModel):
    """Response model for webhook statistics."""
    total_webhooks: int
    enabled_webhooks: int
    total_notifications: int
    failed_notifications: int
    success_rate: float


# CRUD Endpoints

@router.get("/webhooks", response_model=List[WebhookResponse])
async def list_webhooks(
    enabled_only: bool = Query(False, description="Filter to only enabled webhooks"),
    webhook_type: Optional[str] = Query(None, description="Filter by webhook type"),
    db: AsyncSession = Depends(get_db),
):
    """List all configured webhooks."""
    query = select(Webhook)
    
    if enabled_only:
        query = query.where(Webhook.enabled == True)
    
    if webhook_type:
        query = query.where(Webhook.webhook_type == webhook_type)
    
    result = await db.execute(query)
    webhooks = result.scalars().all()
    
    return webhooks


@router.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    webhook_data: WebhookCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook configuration."""
    # Validate JSON fields
    if webhook_data.headers:
        try:
            json.loads(webhook_data.headers)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in headers field")
    
    if webhook_data.filters:
        try:
            json.loads(webhook_data.filters)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in filters field")
    
    # Validate Telegram requirements
    if webhook_data.webhook_type == "telegram":
        if not webhook_data.telegram_chat_id or not webhook_data.telegram_bot_token:
            raise HTTPException(
                400,
                "Telegram webhooks require telegram_chat_id and telegram_bot_token"
            )
    
    webhook = Webhook(
        name=webhook_data.name,
        url=webhook_data.url,
        webhook_type=webhook_data.webhook_type,
        enabled=webhook_data.enabled,
        template=webhook_data.template,
        headers=webhook_data.headers,
        filters=webhook_data.filters,
        telegram_chat_id=webhook_data.telegram_chat_id,
        telegram_bot_token=webhook_data.telegram_bot_token,
        created_at=datetime.utcnow(),
    )
    
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    
    logger.info(f"Created webhook {webhook.id}: {webhook.name}")
    
    return webhook


@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific webhook by ID."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    
    return webhook


@router.put("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: int,
    webhook_data: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook configuration."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    
    # Update fields if provided
    update_data = webhook_data.model_dump(exclude_unset=True)
    
    # Validate JSON fields
    if "headers" in update_data and update_data["headers"]:
        try:
            json.loads(update_data["headers"])
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in headers field")
    
    if "filters" in update_data and update_data["filters"]:
        try:
            json.loads(update_data["filters"])
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in filters field")
    
    for key, value in update_data.items():
        setattr(webhook, key, value)
    
    await db.commit()
    await db.refresh(webhook)
    
    logger.info(f"Updated webhook {webhook.id}")
    
    return webhook


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook configuration."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    
    await db.delete(webhook)
    await db.commit()
    
    logger.info(f"Deleted webhook {webhook_id}")
    
    return {"message": "Webhook deleted"}


# Test Endpoint

@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResult)
async def test_webhook(
    webhook_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Test a webhook by sending a sample notification."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id)
    )
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    
    success, message = await webhook_manager.test_webhook(db, webhook)
    
    return WebhookTestResult(success=success, message=message)


# History Endpoints

@router.get("/history", response_model=List[NotificationHistoryResponse])
async def list_notification_history(
    webhook_id: Optional[int] = Query(None, description="Filter by webhook ID"),
    status: Optional[str] = Query(None, description="Filter by status (sent/failed)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List notification history."""
    query = select(NotificationHistory).order_by(desc(NotificationHistory.sent_at))
    
    if webhook_id:
        query = query.where(NotificationHistory.webhook_id == webhook_id)
    
    if status:
        query = query.where(NotificationHistory.status == status)
    
    query = query.offset(offset).limit(limit)
    
    result = await db.execute(query)
    history = result.scalars().all()
    
    return history


@router.get("/stats", response_model=WebhookStats)
async def get_notification_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get notification statistics."""
    # Count webhooks
    total_result = await db.execute(select(func.count()).select_from(Webhook))
    total_webhooks = total_result.scalar() or 0
    
    enabled_result = await db.execute(
        select(func.count()).select_from(Webhook).where(Webhook.enabled == True)
    )
    enabled_webhooks = enabled_result.scalar() or 0
    
    # Count notifications
    total_notif_result = await db.execute(
        select(func.count()).select_from(NotificationHistory)
    )
    total_notifications = total_notif_result.scalar() or 0
    
    failed_result = await db.execute(
        select(func.count())
        .select_from(NotificationHistory)
        .where(NotificationHistory.status == "failed")
    )
    failed_notifications = failed_result.scalar() or 0
    
    success_rate = 0.0
    if total_notifications > 0:
        success_rate = (total_notifications - failed_notifications) / total_notifications
    
    return WebhookStats(
        total_webhooks=total_webhooks,
        enabled_webhooks=enabled_webhooks,
        total_notifications=total_notifications,
        failed_notifications=failed_notifications,
        success_rate=success_rate,
    )


@router.delete("/history")
async def clear_notification_history(
    older_than_days: int = Query(30, ge=1, description="Delete history older than N days"),
    db: AsyncSession = Depends(get_db),
):
    """Clear old notification history."""
    from datetime import timedelta
    from sqlalchemy import delete
    
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    
    # Count before delete
    count_result = await db.execute(
        select(func.count())
        .select_from(NotificationHistory)
        .where(NotificationHistory.sent_at < cutoff)
    )
    count = count_result.scalar() or 0
    
    # Delete old records
    await db.execute(
        delete(NotificationHistory).where(NotificationHistory.sent_at < cutoff)
    )
    await db.commit()
    
    logger.info(f"Cleared {count} notification history records older than {older_than_days} days")
    
    return {"message": f"Deleted {count} records"}
