"""Store category configuration API routes."""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import StoreCategory
from src.ingest.category_extractor import extract_category_from_product

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    """Request model for creating a store category."""
    store: str
    category_name: str
    category_url: str
    enabled: bool = True
    max_pages: int = 2
    scan_interval_minutes: int = 30
    priority: int = 1
    keywords: Optional[str] = None  # JSON array string
    exclude_keywords: Optional[str] = None  # JSON array string
    brands: Optional[str] = None  # JSON array string
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_discount_percent: Optional[float] = None
    msrp_threshold: Optional[float] = None


class CategoryUpdate(BaseModel):
    """Request model for updating a store category."""
    category_name: Optional[str] = None
    category_url: Optional[str] = None
    enabled: Optional[bool] = None
    max_pages: Optional[int] = None
    scan_interval_minutes: Optional[int] = None
    priority: Optional[int] = None
    keywords: Optional[str] = None
    exclude_keywords: Optional[str] = None
    brands: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_discount_percent: Optional[float] = None
    msrp_threshold: Optional[float] = None


class CategoryResponse(BaseModel):
    """Response model for store category."""
    id: int
    store: str
    category_name: str
    category_url: str
    enabled: bool
    last_scanned: Optional[datetime]
    last_error: Optional[str]
    last_error_at: Optional[datetime]
    products_found: int
    deals_found: int
    created_at: datetime
    max_pages: int
    scan_interval_minutes: int
    priority: int
    keywords: Optional[str]
    exclude_keywords: Optional[str]
    brands: Optional[str]
    min_price: Optional[float]
    max_price: Optional[float]
    min_discount_percent: Optional[float]
    msrp_threshold: Optional[float]

    class Config:
        from_attributes = True


class CategoryDiscoveryResponse(BaseModel):
    """Response model for category discovery."""
    category_url: str
    category_name: str
    store: str
    confidence: float
    message: Optional[str] = None
    category_id: Optional[int] = None  # Set if auto_create was used


@router.get("", response_model=List[CategoryResponse])
async def list_categories(
    store: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
):
    """List all store categories, optionally filtered by store."""
    query = select(StoreCategory).order_by(StoreCategory.store, StoreCategory.category_name)
    
    if store:
        query = query.where(StoreCategory.store == store)
    
    result = await db.execute(query)
    categories = result.scalars().all()
    return categories


@router.post("/discover-from-product", response_model=CategoryDiscoveryResponse)
async def discover_category_from_product(
    product_url: str,
    auto_create: bool = False,
    db: AsyncSession = Depends(get_database),
):
    """Discover a category URL from a product URL, optionally create it."""
    if not product_url or not product_url.strip():
        raise HTTPException(status_code=400, detail="product_url is required")

    product_url = product_url.strip()
    category_info = await extract_category_from_product(product_url)
    if not category_info:
        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to discover category. The product page may be blocked "
                "or the category structure is not supported."
            ),
        )

    if not auto_create:
        return CategoryDiscoveryResponse(
            category_url=category_info.category_url,
            category_name=category_info.category_name,
            store=category_info.store,
            confidence=category_info.confidence,
            message="Category discovered. Click 'Add Category' to save it.",
        )

    # Check for existing category
    existing_query = select(StoreCategory).where(
        StoreCategory.store == category_info.store,
        StoreCategory.category_url == category_info.category_url,
    )
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()
    if existing:
        return CategoryDiscoveryResponse(
            category_url=existing.category_url,
            category_name=existing.category_name,
            store=existing.store,
            confidence=category_info.confidence,
            message="Category already exists.",
            category_id=existing.id,
        )

    # Apply smart defaults from README
    category = StoreCategory(
        store=category_info.store,
        category_name=category_info.category_name,
        category_url=category_info.category_url,
        enabled=True,
        max_pages=5,
        scan_interval_minutes=5,
        priority=8,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)

    return CategoryDiscoveryResponse(
        category_url=category.category_url,
        category_name=category.category_name,
        store=category.store,
        confidence=category_info.confidence,
        message="Category created successfully.",
        category_id=category.id,
    )


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(
    category_data: CategoryCreate,
    db: AsyncSession = Depends(get_database)
):
    """Create a new store category for scanning."""
    from decimal import Decimal
    
    # Check for duplicate
    existing_query = select(StoreCategory).where(
        StoreCategory.store == category_data.store,
        StoreCategory.category_url == category_data.category_url
    )
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Category with this URL already exists for this store"
        )

    category = StoreCategory(
        store=category_data.store,
        category_name=category_data.category_name,
        category_url=category_data.category_url,
        enabled=category_data.enabled,
        max_pages=category_data.max_pages,
        scan_interval_minutes=category_data.scan_interval_minutes,
        priority=category_data.priority,
        keywords=category_data.keywords,
        exclude_keywords=category_data.exclude_keywords,
        brands=category_data.brands,
        min_price=Decimal(str(category_data.min_price)) if category_data.min_price else None,
        max_price=Decimal(str(category_data.max_price)) if category_data.max_price else None,
        min_discount_percent=category_data.min_discount_percent,
        msrp_threshold=category_data.msrp_threshold,
    )

    db.add(category)
    await db.commit()
    await db.refresh(category)

    return category


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(category_id: int, db: AsyncSession = Depends(get_database)):
    """Get a specific store category."""
    query = select(StoreCategory).where(StoreCategory.id == category_id)
    result = await db.execute(query)
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    return category


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    db: AsyncSession = Depends(get_database)
):
    """Update a store category."""
    from decimal import Decimal
    
    query = select(StoreCategory).where(StoreCategory.id == category_id)
    result = await db.execute(query)
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    if category_data.category_name is not None:
        category.category_name = category_data.category_name
    if category_data.category_url is not None:
        category.category_url = category_data.category_url
    if category_data.enabled is not None:
        category.enabled = category_data.enabled
    if category_data.max_pages is not None:
        category.max_pages = category_data.max_pages
    if category_data.scan_interval_minutes is not None:
        category.scan_interval_minutes = category_data.scan_interval_minutes
    if category_data.priority is not None:
        category.priority = category_data.priority
    if category_data.keywords is not None:
        category.keywords = category_data.keywords
    if category_data.exclude_keywords is not None:
        category.exclude_keywords = category_data.exclude_keywords
    if category_data.brands is not None:
        category.brands = category_data.brands
    if category_data.min_price is not None:
        category.min_price = Decimal(str(category_data.min_price))
    if category_data.max_price is not None:
        category.max_price = Decimal(str(category_data.max_price))
    if category_data.min_discount_percent is not None:
        category.min_discount_percent = category_data.min_discount_percent
    if category_data.msrp_threshold is not None:
        category.msrp_threshold = category_data.msrp_threshold

    await db.commit()
    await db.refresh(category)

    return category


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: int, db: AsyncSession = Depends(get_database)):
    """Delete a store category."""
    query = select(StoreCategory).where(StoreCategory.id == category_id)
    result = await db.execute(query)
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    await db.delete(category)
    await db.commit()


@router.get("/stores/list")
async def list_stores_with_categories(db: AsyncSession = Depends(get_database)):
    """Get list of stores with category counts."""
    from sqlalchemy import func, Integer
    
    query = select(
        StoreCategory.store,
        func.count(StoreCategory.id).label("total"),
        func.sum(func.cast(StoreCategory.enabled, Integer)).label("enabled"),
    ).group_by(StoreCategory.store)
    
    result = await db.execute(query)
    rows = result.all()
    
    return [
        {
            "store": row.store,
            "total_categories": row.total,
            "enabled_categories": row.enabled or 0,
        }
        for row in rows
    ]


# Pre-defined category templates for easy setup
CATEGORY_TEMPLATES = {
    "amazon_us": [
        {"name": "Electronics Deals", "url": "/s?k=electronics&deals-widget=%2522"},
        {"name": "Home & Kitchen Deals", "url": "/s?k=home+kitchen&deals-widget=%2522"},
        {"name": "Computers", "url": "/s?k=computers&deals-widget=%2522"},
        {"name": "Appliances", "url": "/s?k=appliances&deals-widget=%2522"},
    ],
    "walmart": [
        {"name": "Rollbacks", "url": "/browse/rollbacks"},
        {"name": "Electronics", "url": "/browse/electronics/3944"},
        {"name": "Home", "url": "/browse/home/4044"},
        {"name": "Appliances", "url": "/browse/appliances/3702"},
    ],
    "bestbuy": [
        {"name": "Deal of the Day", "url": "/site/deal-of-the-day"},
        {"name": "Electronics Deals", "url": "/site/electronics/deals"},
        {"name": "TV Deals", "url": "/site/tvs/deals"},
        {"name": "Laptop Deals", "url": "/site/laptop-computers/deals"},
    ],
    "target": [
        {"name": "Clearance", "url": "/c/clearance/-/N-5q0ga"},
        {"name": "Electronics Deals", "url": "/c/electronics-deals/-/N-5xtfr"},
        {"name": "Home Deals", "url": "/c/home-deals/-/N-5xtvf"},
    ],
    "costco": [
        {"name": "Electronics", "url": "/c/electronics.html"},
        {"name": "Appliances", "url": "/c/appliances.html"},
        {"name": "Home", "url": "/c/home.html"},
    ],
    "macys": [
        {"name": "Sale & Clearance", "url": "/shop/sale"},
        {"name": "Electronics", "url": "/shop/electronics"},
        {"name": "Home", "url": "/shop/home/sale"},
    ],
    "homedepot": [
        {"name": "Special Buys", "url": "/b/Special-Values/N-5yc1v"},
        {"name": "Appliances", "url": "/b/Appliances/N-5yc1vZbv1w"},
        {"name": "Tools", "url": "/b/Tools/N-5yc1vZc1xy"},
    ],
    "lowes": [
        {"name": "Weekly Ad", "url": "/weekly-ad"},
        {"name": "Appliances", "url": "/c/Appliances"},
        {"name": "Tools", "url": "/c/Tools"},
    ],
}


@router.get("/templates/{store}")
async def get_category_templates(store: str):
    """Get pre-defined category templates for a store."""
    if store not in CATEGORY_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"No templates for store: {store}")
    
    return CATEGORY_TEMPLATES[store]


@router.post("/templates/{store}/apply")
async def apply_category_templates(
    store: str,
    db: AsyncSession = Depends(get_database)
):
    """Apply all category templates for a store."""
    if store not in CATEGORY_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"No templates for store: {store}")
    
    templates = CATEGORY_TEMPLATES[store]
    added = 0
    skipped = 0
    
    for template in templates:
        # Check if already exists
        existing_query = select(StoreCategory).where(
            StoreCategory.store == store,
            StoreCategory.category_url == template["url"]
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue
        
        category = StoreCategory(
            store=store,
            category_name=template["name"],
            category_url=template["url"],
            enabled=True,
        )
        db.add(category)
        added += 1
    
    await db.commit()
    
    return {
        "message": f"Added {added} categories, skipped {skipped} existing",
        "added": added,
        "skipped": skipped,
    }
