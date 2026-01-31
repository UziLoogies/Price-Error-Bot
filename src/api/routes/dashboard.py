"""Dashboard API endpoints for the UI."""

from datetime import datetime, timedelta
from collections import deque
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db
from src.db.models import Product, Alert, PriceHistory

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# In-memory scan log (stores last 50 scans)
# This will be populated by the worker when scans happen
_scan_log: deque = deque(maxlen=100)
_scan_id_counter = 0


def add_scan_entry(
    store: str,
    sku: str,
    title: str,
    status: str,
    price: Optional[float] = None,
    previous_price: Optional[float] = None,
    error: Optional[str] = None
):
    """Add a scan entry to the log (called from worker/tasks.py)."""
    global _scan_id_counter
    _scan_id_counter += 1
    
    # Calculate price change percentage
    price_change = None
    if price is not None and previous_price is not None and previous_price > 0:
        price_change = ((price - previous_price) / previous_price) * 100
    
    _scan_log.appendleft({
        "id": _scan_id_counter,
        "store": store,
        "sku": sku,
        "title": title[:50] + "..." if len(title) > 50 else title,
        "status": status,
        "price": price,
        "previousPrice": previous_price,
        "priceChange": price_change,
        "error": error,
        "time": datetime.now().strftime("%H:%M:%S")
    })


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Get summary statistics for the dashboard."""
    
    # Count products
    products_result = await db.execute(select(func.count(Product.id)))
    products_count = products_result.scalar() or 0
    
    # Count unique stores
    stores_result = await db.execute(
        select(func.count(func.distinct(Product.store)))
    )
    stores_count = stores_result.scalar() or 0
    
    # Count alerts today
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    alerts_result = await db.execute(
        select(func.count(Alert.id)).where(Alert.sent_at >= today_start)
    )
    alerts_today = alerts_result.scalar() or 0
    
    return {
        "products": products_count,
        "stores": stores_count,
        "alerts": alerts_today
    }


@router.get("/scans")
async def get_scan_log():
    """Get recent scan activity."""
    return list(_scan_log)


@router.get("/activity")
async def get_recent_activity(db: AsyncSession = Depends(get_db), limit: int = 20):
    """Get recent price history activity."""
    
    result = await db.execute(
        select(PriceHistory)
        .order_by(PriceHistory.fetched_at.desc())
        .limit(limit)
    )
    history = result.scalars().all()
    
    activities = []
    for h in history:
        # Get product info
        product_result = await db.execute(
            select(Product).where(Product.id == h.product_id)
        )
        product = product_result.scalar_one_or_none()
        
        activities.append({
            "id": h.id,
            "product_id": h.product_id,
            "title": product.title if product else "Unknown",
            "store": product.store if product else "Unknown",
            "sku": product.sku if product else "Unknown",
            "price": float(h.price) if h.price else None,
            "time": h.fetched_at.strftime("%Y-%m-%d %H:%M:%S") if h.fetched_at else None
        })
    
    return activities


@router.get("/deals")
async def get_discovered_deals(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
):
    """
    Get all discovered deals (latest price history per product).
    
    Args:
        skip: Number of records to skip (for pagination)
        limit: Maximum number of records to return (default 50, max 200)
    """
    # Enforce maximum limit
    limit = min(limit, 200)
    
    # Latest price history per product
    latest_subq = (
        select(
            PriceHistory.product_id,
            func.max(PriceHistory.fetched_at).label("latest_fetched_at"),
        )
        .group_by(PriceHistory.product_id)
        .subquery()
    )

    # Base query structure (same filters/joins for both count and data)
    base_join_conditions = and_(
        PriceHistory.product_id == latest_subq.c.product_id,
        PriceHistory.fetched_at == latest_subq.c.latest_fetched_at,
    )

    # Count total matching records (without limit/offset)
    count_query = (
        select(func.count(PriceHistory.id))
        .join(
            latest_subq,
            base_join_conditions,
        )
        .join(Product, Product.id == PriceHistory.product_id)
    )
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    # Query with pagination
    query = (
        select(PriceHistory, Product)
        .join(
            latest_subq,
            base_join_conditions,
        )
        .join(Product, Product.id == PriceHistory.product_id)
        .order_by(PriceHistory.fetched_at.desc())
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    deals = []
    for price_history, product in rows:
        orig = price_history.original_price or product.msrp
        discount_percent = None
        if orig and price_history.price and orig > 0:
            discount_percent = float((orig - price_history.price) / orig * 100)

        deals.append(
            {
                "id": price_history.id,
                "product_id": product.id,
                "store": product.store,
                "sku": product.sku,
                "title": product.title,
                "url": product.url,
                "price": float(price_history.price) if price_history.price else None,
                "original_price": float(price_history.original_price) if price_history.original_price else None,
                "msrp": float(product.msrp) if product.msrp else None,
                "discount_percent": discount_percent,
                "timestamp": price_history.fetched_at.isoformat() if price_history.fetched_at else None,
            }
        )

    return {
        "deals": deals,
        "skip": skip,
        "limit": limit,
        "count": len(deals),
        "total_count": total_count
    }
