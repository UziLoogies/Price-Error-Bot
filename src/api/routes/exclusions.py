"""Product exclusions API endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import ProductExclusion

router = APIRouter(prefix="/api/exclusions", tags=["exclusions"])


class ExclusionCreate(BaseModel):
    """Request model for creating an exclusion."""
    store: str
    sku: Optional[str] = None
    keyword: Optional[str] = None
    brand: Optional[str] = None
    reason: Optional[str] = None
    enabled: bool = True


class ExclusionUpdate(BaseModel):
    """Request model for updating an exclusion."""
    sku: Optional[str] = None
    keyword: Optional[str] = None
    brand: Optional[str] = None
    reason: Optional[str] = None
    enabled: Optional[bool] = None


class ExclusionResponse(BaseModel):
    """Response model for exclusion."""
    id: int
    store: str
    sku: Optional[str]
    keyword: Optional[str]
    brand: Optional[str]
    reason: Optional[str]
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[ExclusionResponse])
async def list_exclusions(
    store: Optional[str] = None,
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_database)
):
    """List all product exclusions."""
    query = select(ProductExclusion).order_by(ProductExclusion.created_at.desc())
    
    if store:
        query = query.where(ProductExclusion.store == store)
    
    if enabled_only:
        query = query.where(ProductExclusion.enabled == True)
    
    result = await db.execute(query)
    exclusions = result.scalars().all()
    return exclusions


@router.post("", response_model=ExclusionResponse, status_code=201)
async def create_exclusion(
    exclusion_data: ExclusionCreate,
    db: AsyncSession = Depends(get_database)
):
    """Create a new product exclusion."""
    # Validate that at least one filter is provided
    if not exclusion_data.sku and not exclusion_data.keyword and not exclusion_data.brand:
        raise HTTPException(
            status_code=400,
            detail="At least one of sku, keyword, or brand must be provided"
        )
    
    exclusion = ProductExclusion(
        store=exclusion_data.store,
        sku=exclusion_data.sku,
        keyword=exclusion_data.keyword,
        brand=exclusion_data.brand,
        reason=exclusion_data.reason,
        enabled=exclusion_data.enabled,
    )
    
    db.add(exclusion)
    await db.commit()
    await db.refresh(exclusion)
    
    return exclusion


@router.get("/{exclusion_id}", response_model=ExclusionResponse)
async def get_exclusion(
    exclusion_id: int,
    db: AsyncSession = Depends(get_database)
):
    """Get a specific exclusion."""
    exclusion = await db.get(ProductExclusion, exclusion_id)
    if not exclusion:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    return exclusion


@router.put("/{exclusion_id}", response_model=ExclusionResponse)
async def update_exclusion(
    exclusion_id: int,
    exclusion_data: ExclusionUpdate,
    db: AsyncSession = Depends(get_database)
):
    """Update an exclusion."""
    exclusion = await db.get(ProductExclusion, exclusion_id)
    if not exclusion:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    
    if exclusion_data.sku is not None:
        exclusion.sku = exclusion_data.sku
    if exclusion_data.keyword is not None:
        exclusion.keyword = exclusion_data.keyword
    if exclusion_data.brand is not None:
        exclusion.brand = exclusion_data.brand
    if exclusion_data.reason is not None:
        exclusion.reason = exclusion_data.reason
    if exclusion_data.enabled is not None:
        exclusion.enabled = exclusion_data.enabled
    
    await db.commit()
    await db.refresh(exclusion)
    
    return exclusion


@router.delete("/{exclusion_id}", status_code=204)
async def delete_exclusion(
    exclusion_id: int,
    db: AsyncSession = Depends(get_database)
):
    """Delete an exclusion."""
    exclusion = await db.get(ProductExclusion, exclusion_id)
    if not exclusion:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    
    await db.delete(exclusion)
    await db.commit()


@router.post("/bulk", response_model=dict)
async def create_bulk_exclusions(
    exclusions: List[ExclusionCreate],
    db: AsyncSession = Depends(get_database)
):
    """Create multiple exclusions at once."""
    created = 0
    errors = []
    
    for exc_data in exclusions:
        try:
            if not exc_data.sku and not exc_data.keyword and not exc_data.brand:
                errors.append(f"Exclusion for {exc_data.store} missing filter")
                continue
            
            exclusion = ProductExclusion(
                store=exc_data.store,
                sku=exc_data.sku,
                keyword=exc_data.keyword,
                brand=exc_data.brand,
                reason=exc_data.reason,
                enabled=exc_data.enabled,
            )
            db.add(exclusion)
            created += 1
        except Exception as e:
            errors.append(str(e))
    
    await db.commit()
    
    return {
        "created": created,
        "errors": errors,
    }


@router.get("/stores/summary")
async def get_exclusion_summary(db: AsyncSession = Depends(get_database)):
    """Get summary of exclusions by store."""
    from sqlalchemy import func, Integer, cast
    
    query = select(
        ProductExclusion.store,
        func.count(ProductExclusion.id).label("total"),
        func.sum(cast(ProductExclusion.enabled, Integer)).label("enabled"),
    ).group_by(ProductExclusion.store)
    
    result = await db.execute(query)
    rows = result.all()
    
    return [
        {
            "store": row.store,
            "total_exclusions": row.total,
            "enabled_exclusions": row.enabled or 0,
        }
        for row in rows
    ]
