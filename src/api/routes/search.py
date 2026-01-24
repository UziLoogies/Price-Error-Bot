"""
Enhanced search API endpoints.

Provides comprehensive search functionality across all entities with:
- Full-text search with PostgreSQL tsvector/tsquery
- Advanced filtering and sorting
- Cursor-based pagination
- Search suggestions and autocomplete
- Search analytics and caching
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.search.service import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Initialize search service (will be enhanced with Redis later)
search_service = SearchService()

# ============================================================================
# Request/Response Models
# ============================================================================


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class EntityType(str, Enum):
    PRODUCTS = "products"
    ALERTS = "alerts"
    CATEGORIES = "categories"
    SCAN_JOBS = "scan_jobs"


class ProductSortBy(str, Enum):
    RELEVANCE = "relevance"
    CREATED_AT = "created_at"
    TITLE = "title"
    PRICE = "msrp"
    DISCOUNT = "discount"


class AlertSortBy(str, Enum):
    SENT_AT = "sent_at"
    DISCOUNT_PERCENT = "discount_percent"
    PRICE_DROP = "price_drop"


class SearchFilters(BaseModel):
    """Common search filters."""

    stores: Optional[List[str]] = Field(None, max_items=10, description="Store filters")
    date_from: Optional[datetime] = Field(None, description="Filter by date range start")
    date_to: Optional[datetime] = Field(None, description="Filter by date range end")
    active_only: Optional[bool] = Field(False, description="Show only active/enabled items")

    @validator("date_to")
    def date_to_after_date_from(cls, v, values):
        if v and "date_from" in values and values["date_from"]:
            if v <= values["date_from"]:
                raise ValueError("date_to must be after date_from")
        return v


class ProductSearchFilters(SearchFilters):
    """Product-specific search filters."""

    price_min: Optional[float] = Field(None, ge=0, description="Minimum price")
    price_max: Optional[float] = Field(None, ge=0, description="Maximum price")
    discount_min: Optional[float] = Field(None, ge=0, le=100, description="Minimum discount %")
    has_alerts: Optional[bool] = Field(None, description="Has price alerts")
    in_stock: Optional[bool] = Field(None, description="Currently in stock")

    @validator("price_max")
    def price_max_greater_than_min(cls, v, values):
        if v and "price_min" in values and values["price_min"]:
            if v <= values["price_min"]:
                raise ValueError("price_max must be greater than price_min")
        return v


class AlertSearchFilters(SearchFilters):
    """Alert-specific search filters."""

    price_min: Optional[float] = Field(None, ge=0, description="Minimum triggered price")
    price_max: Optional[float] = Field(None, ge=0, description="Maximum triggered price")
    discount_min: Optional[float] = Field(None, ge=0, le=100, description="Minimum discount %")
    discount_max: Optional[float] = Field(None, ge=0, le=100, description="Maximum discount %")
    rule_type: Optional[List[str]] = Field(None, description="Filter by rule types")
    has_message_id: Optional[bool] = Field(None, description="Has Discord message ID")


class PaginationParams(BaseModel):
    """Pagination parameters."""

    cursor: Optional[str] = Field(None, description="Pagination cursor")
    limit: int = Field(20, ge=1, le=100, description="Results per page")


class SearchHighlight(BaseModel):
    """Search term highlighting in results."""

    field_name: str
    highlighted_text: List[str]


class FacetOption(BaseModel):
    """Facet option with count."""

    name: str
    count: int
    display_name: Optional[str] = None


class PaginationInfo(BaseModel):
    """Pagination information."""

    has_next: bool
    has_previous: bool
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    limit: int
    total_count: Optional[int] = None


class QueryInfo(BaseModel):
    """Search query metadata."""

    query: str
    processed_query: Optional[str] = None
    response_time_ms: int
    total_results: int
    uses_fts: Optional[bool] = None
    uses_trigram: Optional[bool] = None
    error: Optional[str] = None


# ============================================================================
# Response Models
# ============================================================================


class ProductSearchResult(BaseModel):
    """Product search result."""

    id: int
    sku: str
    store: str
    title: Optional[str]
    url: Optional[str]
    image_url: Optional[str]
    msrp: Optional[float]
    baseline_price: Optional[float]
    current_price: Optional[float]
    discount_percent: Optional[float]
    in_stock: Optional[bool]
    created_at: str
    search_score: float
    highlights: Dict[str, List[str]] = Field(default_factory=dict)


class AlertSearchResult(BaseModel):
    """Alert search result."""

    id: int
    product_id: int
    rule_id: int
    triggered_price: float
    previous_price: Optional[float]
    discount_percent: Optional[float]
    discord_message_id: Optional[str]
    sent_at: str
    highlights: Dict[str, List[str]] = Field(default_factory=dict)


class ProductSearchResponse(BaseModel):
    """Product search response."""

    products: List[ProductSearchResult]
    pagination: PaginationInfo
    facets: Dict[str, List[FacetOption]]
    query_info: QueryInfo


class AlertSearchResponse(BaseModel):
    """Alert search response."""

    alerts: List[AlertSearchResult]
    pagination: PaginationInfo
    facets: Dict[str, List[FacetOption]]
    query_info: QueryInfo


class SearchSuggestion(BaseModel):
    """Search suggestion."""

    text: str
    type: str
    count: int
    highlight: Optional[str] = None


class RecentSearch(BaseModel):
    """Recent search query."""

    query: str
    timestamp: str


class PopularSearch(BaseModel):
    """Popular search query."""

    query: str
    count: int


class SuggestionsResponse(BaseModel):
    """Search suggestions response."""

    suggestions: List[SearchSuggestion]
    recent_searches: List[RecentSearch]
    popular_searches: List[PopularSearch]


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/products", response_model=ProductSearchResponse)
async def search_products(
    q: Optional[str] = Query(None, min_length=1, max_length=500, description="Search query"),
    sku: Optional[str] = Query(None, description="SKU exact or partial match"),
    title: Optional[str] = Query(None, description="Title contains text"),
    # Filters
    stores: Optional[List[str]] = Query(None, description="Store filters"),
    price_min: Optional[float] = Query(None, ge=0, description="Minimum price"),
    price_max: Optional[float] = Query(None, ge=0, description="Maximum price"),
    discount_min: Optional[float] = Query(None, ge=0, le=100, description="Minimum discount %"),
    has_alerts: Optional[bool] = Query(None, description="Has price alerts"),
    in_stock: Optional[bool] = Query(None, description="Currently in stock"),
    created_after: Optional[datetime] = Query(None, description="Created after date"),
    created_before: Optional[datetime] = Query(None, description="Created before date"),
    # Sorting and pagination
    sort_by: ProductSortBy = Query(ProductSortBy.RELEVANCE, description="Sort field"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="Sort order"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    # Additional options
    include_history: bool = Query(False, description="Include recent price history"),
    include_alerts: bool = Query(False, description="Include recent alerts"),
    # Dependencies
    db: AsyncSession = Depends(get_database),
) -> ProductSearchResponse:
    """
    Search products with full-text search and advanced filtering.

    Supports:
    - Full-text search across title, SKU, and store
    - Multiple filter combinations
    - Relevance-based ranking
    - Faceted search results
    - Cursor-based pagination
    """
    try:
        # Validate query length
        if q and len(q) > 500:
            raise HTTPException(
                status_code=400, detail="Search query too long (max 500 characters)"
            )

        # Build filters dict
        filters = {
            k: v
            for k, v in {
                "sku": sku,
                "title": title,
                "store": stores,
                "price_min": price_min,
                "price_max": price_max,
                "discount_min": discount_min,
                "has_alerts": has_alerts,
                "in_stock": in_stock,
                "created_after": created_after,
                "created_before": created_before,
                "sort_by": sort_by.value,
                "sort_order": sort_order.value,
                "cursor": cursor,
                "limit": limit,
                "include_history": include_history,
                "include_alerts": include_alerts,
            }.items()
            if v is not None
        }

        # Perform search
        result = await search_service.search_products(db, query_text=q, **filters)

        # Convert to response format
        return ProductSearchResponse(
            products=[ProductSearchResult(**product) for product in result["products"]],
            pagination=PaginationInfo(**result["pagination"]),
            facets=result["facets"],
            query_info=QueryInfo(**result["query_info"]),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Product search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search temporarily unavailable")


@router.get("/alerts", response_model=AlertSearchResponse)
async def search_alerts(
    q: Optional[str] = Query(None, min_length=1, max_length=500, description="Search query"),
    # Filters
    stores: Optional[List[str]] = Query(None, description="Store filters"),
    price_min: Optional[float] = Query(None, ge=0, description="Minimum triggered price"),
    price_max: Optional[float] = Query(None, ge=0, description="Maximum triggered price"),
    discount_min: Optional[float] = Query(None, ge=0, le=100, description="Minimum discount %"),
    discount_max: Optional[float] = Query(None, ge=0, le=100, description="Maximum discount %"),
    rule_type: Optional[List[str]] = Query(None, description="Rule type filters"),
    sent_after: Optional[datetime] = Query(None, description="Sent after date"),
    sent_before: Optional[datetime] = Query(None, description="Sent before date"),
    has_message_id: Optional[bool] = Query(None, description="Has Discord message ID"),
    # Sorting and pagination
    sort_by: AlertSortBy = Query(AlertSortBy.SENT_AT, description="Sort field"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="Sort order"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    # Dependencies
    db: AsyncSession = Depends(get_database),
) -> AlertSearchResponse:
    """
    Search price alerts with product information.

    Searches across:
    - Product title and SKU (via join)
    - Price ranges and discount percentages
    - Date ranges and rule types
    """
    try:
        if q and len(q) > 500:
            raise HTTPException(
                status_code=400, detail="Search query too long (max 500 characters)"
            )

        filters = {
            k: v
            for k, v in {
                "store": stores,
                "price_min": price_min,
                "price_max": price_max,
                "discount_min": discount_min,
                "discount_max": discount_max,
                "rule_type": rule_type,
                "sent_after": sent_after,
                "sent_before": sent_before,
                "has_message_id": has_message_id,
                "sort_by": sort_by.value,
                "sort_order": sort_order.value,
                "cursor": cursor,
                "limit": limit,
            }.items()
            if v is not None
        }

        result = await search_service.search_alerts(db, query_text=q, **filters)

        return AlertSearchResponse(
            alerts=[AlertSearchResult(**alert) for alert in result["alerts"]],
            pagination=PaginationInfo(**result["pagination"]),
            facets=result["facets"],
            query_info=QueryInfo(**result["query_info"]),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Alert search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search temporarily unavailable")


@router.get("/suggestions", response_model=SuggestionsResponse)
async def get_search_suggestions(
    q: str = Query(..., min_length=2, max_length=200, description="Partial search query"),
    entity_type: EntityType = Query(EntityType.PRODUCTS, description="Entity type for suggestions"),
    field: Optional[str] = Query(None, description="Specific field for suggestions"),
    limit: int = Query(10, ge=1, le=20, description="Maximum suggestions"),
    db: AsyncSession = Depends(get_database),
) -> SuggestionsResponse:
    """
    Get search suggestions and autocomplete data.

    Returns:
    - Field-specific suggestions (title, SKU, etc.)
    - Recent search queries
    - Popular search terms
    """
    try:
        result = await search_service.get_suggestions(
            db, query=q, entity_type=entity_type.value, field=field, limit=limit
        )

        return SuggestionsResponse(
            suggestions=[SearchSuggestion(**s) for s in result["suggestions"]],
            recent_searches=[RecentSearch(**r) for r in result["recent_searches"]],
            popular_searches=[PopularSearch(**p) for p in result["popular_searches"]],
        )

    except Exception as e:
        logger.error(f"Suggestions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Suggestions temporarily unavailable")


@router.get("/universal")
async def universal_search(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    entities: List[EntityType] = Query([EntityType.PRODUCTS], description="Entity types to search"),
    stores: Optional[List[str]] = Query(None, description="Store filters"),
    date_from: Optional[datetime] = Query(None, description="Date range start"),
    date_to: Optional[datetime] = Query(None, description="Date range end"),
    active_only: bool = Query(False, description="Show only active items"),
    sort_by: str = Query("relevance", description="Sort field"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="Sort order"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """
    Universal search across multiple entity types.

    Returns unified results from products, alerts, categories, and scan jobs
    with consistent formatting and relevance ranking.
    """
    try:
        # For MVP, redirect to individual search endpoints
        # This would be implemented as a true universal search later
        results = {}

        if EntityType.PRODUCTS in entities:
            product_result = await search_service.search_products(
                db,
                query_text=q,
                store=stores,
                created_after=date_from,
                created_before=date_to,
                sort_by=sort_by,
                sort_order=sort_order.value,
                limit=limit // len(entities),  # Split limit across entity types
            )
            results["products"] = product_result

        if EntityType.ALERTS in entities:
            alert_result = await search_service.search_alerts(
                db,
                query_text=q,
                store=stores,
                sent_after=date_from,
                sent_before=date_to,
                sort_by="sent_at",
                sort_order=sort_order.value,
                limit=limit // len(entities),
            )
            results["alerts"] = alert_result

        return {
            "results": results,
            "query_info": {
                "query": q,
                "entities": [e.value for e in entities],
                "total_types": len(entities),
            },
        }

    except Exception as e:
        logger.error(f"Universal search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search temporarily unavailable")


# ============================================================================
# Search Analytics (Admin endpoints)
# ============================================================================


@router.get("/analytics/summary")
async def get_search_analytics(
    date_from: Optional[datetime] = Query(None, description="Analytics date range start"),
    date_to: Optional[datetime] = Query(None, description="Analytics date range end"),
    db: AsyncSession = Depends(get_database),
) -> Dict[str, Any]:
    """
    Get search usage analytics and performance metrics.

    Admin endpoint for monitoring search usage and optimization.
    """
    try:
        # This would implement comprehensive search analytics
        # For now, return placeholder data
        return {
            "summary": {
                "total_searches": 0,
                "unique_queries": 0,
                "avg_response_time": 0,
                "success_rate": 1.0,
            },
            "top_queries": [],
            "performance_stats": {
                "p50_response_time": 0,
                "p95_response_time": 0,
                "cache_hit_rate": 0.0,
            },
        }

    except Exception as e:
        logger.error(f"Analytics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Analytics temporarily unavailable")
