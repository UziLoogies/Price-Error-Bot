"""Webhook management routes."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import Webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    name: str | None = None
    url: str
    enabled: bool = True


class WebhookResponse(BaseModel):
    id: int
    name: str | None
    url: str
    enabled: bool

    class Config:
        from_attributes = True


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


@router.get("", response_model=List[WebhookResponse])
async def list_webhooks(db: AsyncSession = Depends(get_database)):
    """List all webhooks."""
    result = await db.execute(select(Webhook).order_by(Webhook.id.asc()))
    webhooks = result.scalars().all()
    return webhooks


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    webhook_data: WebhookCreate, db: AsyncSession = Depends(get_database)
):
    """Create a new webhook."""
    webhook = Webhook(
        name=webhook_data.name,
        url=webhook_data.url,
        enabled=webhook_data.enabled,
    )

    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    return webhook


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: int, db: AsyncSession = Depends(get_database)
):
    """Get a webhook by ID."""
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return webhook


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: int,
    webhook_data: WebhookUpdate,
    db: AsyncSession = Depends(get_database),
):
    """Update a webhook."""
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if webhook_data.name is not None:
        webhook.name = webhook_data.name
    if webhook_data.url is not None:
        webhook.url = webhook_data.url
    if webhook_data.enabled is not None:
        webhook.enabled = webhook_data.enabled

    await db.commit()
    await db.refresh(webhook)

    return webhook


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: int, db: AsyncSession = Depends(get_database)
):
    """Delete a webhook."""
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.execute(delete(Webhook).where(Webhook.id == webhook_id))
    await db.commit()

    return None
