"""Rule management routes."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import Rule as RuleModel

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleCreate(BaseModel):
    name: str | None = None
    rule_type: str
    threshold: float
    enabled: bool = True
    priority: int = 0


class RuleResponse(BaseModel):
    id: int
    name: str | None
    rule_type: str
    threshold: float
    enabled: bool
    priority: int

    class Config:
        from_attributes = True


class RuleUpdate(BaseModel):
    name: str | None = None
    rule_type: str | None = None
    threshold: float | None = None
    enabled: bool | None = None
    priority: int | None = None


@router.get("", response_model=List[RuleResponse])
async def list_rules(db: AsyncSession = Depends(get_database)):
    """List all rules."""
    result = await db.execute(
        select(RuleModel).order_by(RuleModel.priority.desc(), RuleModel.id.asc())
    )
    rules = result.scalars().all()
    return rules


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    rule_data: RuleCreate, db: AsyncSession = Depends(get_database)
):
    """Create a new rule."""
    rule = RuleModel(
        name=rule_data.name,
        rule_type=rule_data.rule_type,
        threshold=rule_data.threshold,
        enabled=rule_data.enabled,
        priority=rule_data.priority,
    )

    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return rule


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: int, db: AsyncSession = Depends(get_database)):
    """Get a rule by ID."""
    result = await db.execute(select(RuleModel).where(RuleModel.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: RuleUpdate,
    db: AsyncSession = Depends(get_database),
):
    """Update a rule."""
    result = await db.execute(select(RuleModel).where(RuleModel.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if rule_data.name is not None:
        rule.name = rule_data.name
    if rule_data.rule_type is not None:
        rule.rule_type = rule_data.rule_type
    if rule_data.threshold is not None:
        rule.threshold = rule_data.threshold
    if rule_data.enabled is not None:
        rule.enabled = rule_data.enabled
    if rule_data.priority is not None:
        rule.priority = rule_data.priority

    await db.commit()
    await db.refresh(rule)

    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_database)):
    """Delete a rule."""
    result = await db.execute(select(RuleModel).where(RuleModel.id == rule_id))
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    await db.execute(delete(RuleModel).where(RuleModel.id == rule_id))
    await db.commit()

    return None
