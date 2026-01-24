"""Product management routes."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import PriceHistory, Product
from src.ingest.registry import FetcherRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductCreate(BaseModel):
    sku: str
    store: str = "amazon_us"
    url: str | None = None
    title: str | None = None
    msrp: float | None = None
    baseline_price: float | None = None

    @field_validator("store")
    @classmethod
    def validate_store(cls, v: str) -> str:
        """Validate store name against registry."""
        available_stores = FetcherRegistry.list_stores()
        if v not in available_stores:
            raise ValueError(
                f"Invalid store '{v}'. Available stores: {', '.join(available_stores)}"
            )
        return v


class ProductResponse(BaseModel):
    id: int
    sku: str
    store: str
    url: str | None
    title: str | None
    msrp: float | None
    baseline_price: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class PriceHistoryResponse(BaseModel):
    id: int
    price: float
    shipping: float
    availability: str | None
    confidence: float
    fetched_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[ProductResponse])
async def list_products(db: AsyncSession = Depends(get_database)):
    """List all products."""
    result = await db.execute(select(Product).order_by(Product.created_at.desc()))
    products = result.scalars().all()
    return products


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    product_data: ProductCreate, 
    db: AsyncSession = Depends(get_database),
    validate: bool = Query(True, description="Fetch live data to validate SKU and get real title"),
):
    """
    Create a new product to monitor.
    
    By default, validates the product by fetching live data from the store
    to get the real title and MSRP. Set validate=false to skip validation.
    """
    # Check if product already exists
    existing = await db.execute(
        select(Product).where(
            Product.sku == product_data.sku, Product.store == product_data.store
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Product already exists")

    # Values to use (may be updated from live data)
    final_title = product_data.title
    final_msrp = product_data.msrp
    final_url = product_data.url
    live_price = None

    # Validate by fetching live data
    if validate:
        try:
            fetcher = FetcherRegistry.get_fetcher(product_data.store)
            raw_data = await fetcher.fetch(product_data.sku)
            
            # Use live title (source of truth)
            if raw_data.title:
                if final_title and final_title.lower() != raw_data.title.lower():
                    logger.warning(
                        f"Title mismatch for {product_data.sku}: "
                        f"provided '{final_title}' vs live '{raw_data.title}'"
                    )
                final_title = raw_data.title
            
            # Use live MSRP if available
            if raw_data.msrp:
                final_msrp = float(raw_data.msrp)
            
            # Get URL from fetcher
            if raw_data.url:
                final_url = raw_data.url
            
            # Store live price for baseline
            if raw_data.current_price:
                live_price = float(raw_data.current_price)
                
            logger.info(f"Validated product {product_data.sku}: '{final_title}'")
                
        except Exception as e:
            logger.warning(f"Could not validate product {product_data.sku}: {e}")
            # Still allow adding if fetch fails, but warn user
            if not final_title:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not fetch product data and no title provided: {e}"
                )

    product = Product(
        sku=product_data.sku,
        store=product_data.store,
        url=final_url,
        title=final_title,
        msrp=Decimal(str(final_msrp)) if final_msrp else None,
        baseline_price=Decimal(str(product_data.baseline_price or live_price)) if (product_data.baseline_price or live_price) else None,
    )

    db.add(product)
    await db.commit()
    await db.refresh(product)

    return product


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_database)):
    """Get a product by ID."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return product


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_database)):
    """Delete a product and its related records (price history, alerts)."""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Use ORM delete to trigger cascade deletes for related records
    await db.delete(product)
    await db.commit()

    return None


@router.get("/{product_id}/history", response_model=List[PriceHistoryResponse])
async def get_price_history(
    product_id: int, db: AsyncSession = Depends(get_database)
):
    """Get price history for a product."""
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.fetched_at.desc())
        .limit(100)
    )
    history = result.scalars().all()
    return history
