"""
Search service with caching, analytics, and suggestion management.

Provides high-level search functionality including:
- Cached search results with Redis
- Search analytics and logging
- Suggestion generation and management
- Performance monitoring
"""

import json
import time
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from src.search.query_builder import SearchQueryBuilder
from src.db.models import (
    Product,
    StoreCategory,
    SearchQuery,
)

logger = logging.getLogger(__name__)


class SearchService:
    """High-level search service with caching and analytics."""

    def __init__(self, redis_client=None):
        self.query_builder = SearchQueryBuilder()
        self.redis = redis_client
        self.logger = logger

        # Cache configuration
        self.CACHE_TTL = 300  # 5 minutes
        self.SUGGESTION_CACHE_TTL = 3600  # 1 hour
        self.ANALYTICS_ENABLED = True

    async def search_products(
        self, db: AsyncSession, query_text: Optional[str] = None, **filters
    ) -> Dict[str, Any]:
        """
        Search products with caching and analytics.

        Returns:
            Dict containing products, pagination info, facets, and metadata
        """
        start_time = time.time()

        # Generate cache key
        cache_key = (
            f"search:products:{self.query_builder.calculate_query_hash(q=query_text, **filters)}"
        )

        # Try cache first
        cached_result = await self._get_cached_result(cache_key)
        if cached_result:
            self.logger.debug(f"Cache hit for products search: {cache_key}")
            return cached_result

        try:
            # Build and execute query
            query, metadata = self.query_builder.build_product_search_query(
                query_text=query_text, **filters
            )

            result = await db.execute(query)

            # Handle results with ranking
            if metadata["uses_fts"]:
                # Results include search_rank column
                rows = result.all()
                products = [row[0] for row in rows]  # Extract product objects
                search_ranks = [row[1] if len(row) > 1 else 0 for row in rows]
            else:
                products = result.scalars().all()
                search_ranks = [0] * len(products)

            # Check for next page (we fetched limit + 1)
            limit = filters.get("limit", 20)
            has_next = len(products) > limit
            if has_next:
                products = products[:-1]
                search_ranks = search_ranks[:-1]

            # Get facets
            facets = await self._get_product_facets(db, query_text, filters)

            # Build response
            response_time = int((time.time() - start_time) * 1000)
            result_data = {
                "products": [
                    {
                        "id": p.id,
                        "sku": p.sku,
                        "store": p.store,
                        "title": p.title,
                        "url": p.url,
                        "image_url": p.image_url,
                        "msrp": float(p.msrp) if p.msrp else None,
                        "baseline_price": float(p.baseline_price) if p.baseline_price else None,
                        "created_at": p.created_at.isoformat(),
                        "search_score": search_ranks[i] if i < len(search_ranks) else 0,
                        "highlights": (
                            self._generate_highlights(p, query_text) if query_text else {}
                        ),
                    }
                    for i, p in enumerate(products)
                ],
                "pagination": {
                    "has_next": has_next,
                    "has_previous": False,  # TODO: Implement cursor-based pagination
                    "limit": limit,
                    "total_count": len(products),  # Approximate for performance
                },
                "facets": facets,
                "query_info": {
                    "query": query_text or "",
                    "processed_query": self.query_builder.normalize_query(query_text or ""),
                    "response_time_ms": response_time,
                    "total_results": len(products),
                    "uses_fts": metadata["uses_fts"],
                    "uses_trigram": metadata["uses_trigram"],
                },
            }

            # Cache result
            await self._cache_result(cache_key, result_data)

            # Log analytics
            if self.ANALYTICS_ENABLED:
                await self._log_search_query(
                    db=db,
                    query_text=query_text or "",
                    entity_type="products",
                    filters=filters,
                    result_count=len(products),
                    response_time_ms=response_time,
                )

            return result_data

        except Exception as e:
            self.logger.error(f"Product search failed: {e}", exc_info=True)
            # Return empty result instead of failing
            return {
                "products": [],
                "pagination": {
                    "has_next": False,
                    "has_previous": False,
                    "limit": 0,
                    "total_count": 0,
                },
                "facets": {},
                "query_info": {
                    "query": query_text or "",
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "total_results": 0,
                    "error": str(e),
                },
            }

    async def search_alerts(
        self, db: AsyncSession, query_text: Optional[str] = None, **filters
    ) -> Dict[str, Any]:
        """Search alerts with product information."""
        start_time = time.time()

        cache_key = (
            f"search:alerts:{self.query_builder.calculate_query_hash(q=query_text, **filters)}"
        )
        cached_result = await self._get_cached_result(cache_key)
        if cached_result:
            return cached_result

        try:
            query, metadata = self.query_builder.build_alert_search_query(
                query_text=query_text, **filters
            )

            result = await db.execute(query)
            alerts = result.scalars().all()

            limit = filters.get("limit", 20)
            has_next = len(alerts) > limit
            if has_next:
                alerts = alerts[:-1]

            # Build response with product information
            response_time = int((time.time() - start_time) * 1000)
            result_data = {
                "alerts": [
                    {
                        "id": a.id,
                        "product_id": a.product_id,
                        "rule_id": a.rule_id,
                        "triggered_price": float(a.triggered_price),
                        "previous_price": float(a.previous_price) if a.previous_price else None,
                        "discount_percent": self._calculate_discount_percent(
                            a.triggered_price, a.previous_price
                        ),
                        "discord_message_id": a.discord_message_id,
                        "sent_at": a.sent_at.isoformat(),
                        "highlights": (
                            self._generate_highlights(a, query_text) if query_text else {}
                        ),
                    }
                    for a in alerts
                ],
                "pagination": {
                    "has_next": has_next,
                    "has_previous": False,
                    "limit": limit,
                    "total_count": len(alerts),
                },
                "facets": await self._get_alert_facets(db, query_text, filters),
                "query_info": {
                    "query": query_text or "",
                    "response_time_ms": response_time,
                    "total_results": len(alerts),
                },
            }

            await self._cache_result(cache_key, result_data)

            if self.ANALYTICS_ENABLED:
                await self._log_search_query(
                    db=db,
                    query_text=query_text or "",
                    entity_type="alerts",
                    filters=filters,
                    result_count=len(alerts),
                    response_time_ms=response_time,
                )

            return result_data

        except Exception as e:
            self.logger.error(f"Alert search failed: {e}", exc_info=True)
            return {
                "alerts": [],
                "pagination": {
                    "has_next": False,
                    "has_previous": False,
                    "limit": 0,
                    "total_count": 0,
                },
                "facets": {},
                "query_info": {
                    "query": query_text or "",
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "total_results": 0,
                    "error": str(e),
                },
            }

    async def get_suggestions(
        self,
        db: AsyncSession,
        query: str,
        entity_type: str = "products",
        field: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Get search suggestions and autocomplete data."""
        if len(query) < 2:
            return {"suggestions": [], "recent_searches": [], "popular_searches": []}

        cache_key = f"suggestions:{entity_type}:{field}:{query.lower()}"
        cached_result = await self._get_cached_result(cache_key, ttl=self.SUGGESTION_CACHE_TTL)
        if cached_result:
            return cached_result

        try:
            suggestions = []

            # Generate suggestions based on entity type
            if entity_type == "products":
                suggestions = await self._get_product_suggestions(db, query, field, limit)
            elif entity_type == "categories":
                suggestions = await self._get_category_suggestions(db, query, field, limit)

            # Get recent and popular searches
            recent_searches = await self._get_recent_searches(db, entity_type, limit=5)
            popular_searches = await self._get_popular_searches(db, entity_type, limit=5)

            result_data = {
                "suggestions": suggestions,
                "recent_searches": recent_searches,
                "popular_searches": popular_searches,
            }

            await self._cache_result(cache_key, result_data, ttl=self.SUGGESTION_CACHE_TTL)
            return result_data

        except Exception as e:
            self.logger.error(f"Suggestion generation failed: {e}", exc_info=True)
            return {"suggestions": [], "recent_searches": [], "popular_searches": []}

    async def _get_product_suggestions(
        self, db: AsyncSession, query: str, field: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Generate product-specific suggestions."""
        suggestions = []

        if not field or field == "title":
            # Title suggestions using trigram similarity
            title_query = (
                select(Product.title, func.count().label("count"))
                .where(func.similarity(Product.title, query) > 0.3)
                .group_by(Product.title)
                .order_by(desc("count"))
                .limit(limit)
            )

            result = await db.execute(title_query)
            for title, count in result.all():
                suggestions.append(
                    {
                        "text": title,
                        "type": "product_title",
                        "count": count,
                        "highlight": self._highlight_text(title, query),
                    }
                )

        if not field or field == "sku":
            # SKU suggestions
            sku_query = select(Product.sku).where(Product.sku.ilike(f"%{query}%")).limit(limit // 2)

            result = await db.execute(sku_query)
            for (sku,) in result.all():
                suggestions.append(
                    {
                        "text": sku,
                        "type": "product_sku",
                        "count": 1,
                        "highlight": self._highlight_text(sku, query),
                    }
                )

        return suggestions[:limit]

    async def _get_category_suggestions(
        self, db: AsyncSession, query: str, field: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Generate category-specific suggestions."""
        suggestions = []

        # Category name suggestions
        name_query = (
            select(StoreCategory.category_name, func.count().label("count"))
            .where(func.similarity(StoreCategory.category_name, query) > 0.3)
            .group_by(StoreCategory.category_name)
            .order_by(desc("count"))
            .limit(limit)
        )

        result = await db.execute(name_query)
        for name, count in result.all():
            suggestions.append(
                {
                    "text": name,
                    "type": "category_name",
                    "count": count,
                    "highlight": self._highlight_text(name, query),
                }
            )

        return suggestions

    async def _get_product_facets(
        self, db: AsyncSession, query_text: Optional[str], filters: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Generate faceted search data for products."""
        facets = {}

        try:
            # Store facets
            store_query = select(Product.store, func.count().label("count")).group_by(Product.store)
            result = await db.execute(store_query)

            facets["stores"] = [
                {"name": store, "count": count, "display_name": self._get_store_display_name(store)}
                for store, count in result.all()
            ]

            # Price range facets (dynamic binning)
            price_stats_query = select(
                func.min(Product.msrp).label("min_price"), func.max(Product.msrp).label("max_price")
            ).where(Product.msrp.isnot(None))

            result = await db.execute(price_stats_query)
            min_price, max_price = result.one()

            if min_price and max_price:
                price_ranges = self._generate_price_ranges(min_price, max_price)
                facets["price_ranges"] = price_ranges

        except Exception as e:
            self.logger.error(f"Facet generation failed: {e}")
            facets = {"stores": [], "price_ranges": []}

        return facets

    async def _get_alert_facets(
        self, db: AsyncSession, query_text: Optional[str], filters: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Generate faceted search data for alerts."""
        # Implementation similar to product facets
        return {"stores": [], "discount_ranges": []}

    async def _get_recent_searches(
        self, db: AsyncSession, entity_type: str, limit: int
    ) -> List[Dict[str, str]]:
        """Get recent search queries."""
        query = (
            select(SearchQuery.query_text, SearchQuery.created_at)
            .where(SearchQuery.entity_type == entity_type)
            .order_by(desc(SearchQuery.created_at))
            .limit(limit)
        )

        result = await db.execute(query)
        return [
            {"query": query_text, "timestamp": created_at.isoformat()}
            for query_text, created_at in result.all()
        ]

    async def _get_popular_searches(
        self, db: AsyncSession, entity_type: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Get popular search queries."""
        query = (
            select(SearchQuery.query_text, func.count().label("count"))
            .where(
                SearchQuery.entity_type == entity_type,
                SearchQuery.created_at >= datetime.utcnow() - timedelta(days=30),
            )
            .group_by(SearchQuery.query_text)
            .order_by(desc("count"))
            .limit(limit)
        )

        result = await db.execute(query)
        return [{"query": query_text, "count": count} for query_text, count in result.all()]

    async def _log_search_query(
        self,
        db: AsyncSession,
        query_text: str,
        entity_type: str,
        filters: Dict[str, Any],
        result_count: int,
        response_time_ms: int,
        user_agent: Optional[str] = None,
    ) -> None:
        """Log search query for analytics."""
        try:
            search_query = SearchQuery(
                query_text=query_text,
                entity_type=entity_type,
                filters=filters,
                result_count=result_count,
                response_time_ms=response_time_ms,
                user_agent=user_agent,
            )
            db.add(search_query)
            await db.commit()
        except Exception as e:
            self.logger.error(f"Failed to log search query: {e}")

    async def _get_cached_result(self, key: str, ttl: int = None) -> Optional[Dict[str, Any]]:
        """Get cached search result."""
        if not self.redis:
            return None

        try:
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            self.logger.warning(f"Cache read failed: {e}")

        return None

    async def _cache_result(self, key: str, data: Dict[str, Any], ttl: int = None) -> None:
        """Cache search result."""
        if not self.redis:
            return

        try:
            await self.redis.setex(key, ttl or self.CACHE_TTL, json.dumps(data, default=str))
        except Exception as e:
            self.logger.warning(f"Cache write failed: {e}")

    def _generate_highlights(self, obj: Any, query: str) -> Dict[str, List[str]]:
        """Generate search term highlights for result object."""
        if not query:
            return {}

        highlights = {}
        query_terms = query.lower().split()

        # Highlight in title
        if hasattr(obj, "title") and obj.title:
            highlighted = self._highlight_text(obj.title, query)
            if "<mark>" in highlighted:
                highlights["title"] = [highlighted]

        # Highlight in SKU
        if hasattr(obj, "sku") and obj.sku:
            highlighted = self._highlight_text(obj.sku, query)
            if "<mark>" in highlighted:
                highlights["sku"] = [highlighted]

        return highlights

    def _highlight_text(self, text: str, query: str) -> str:
        """Add highlighting markup to matching terms."""
        if not text or not query:
            return text

        # Simple highlighting - wrap matching terms in <mark> tags
        import re

        pattern = re.compile(re.escape(query), re.IGNORECASE)
        return pattern.sub(r"<mark>\g<0></mark>", text)

    def _calculate_discount_percent(self, current_price, original_price) -> Optional[float]:
        """Calculate discount percentage."""
        if not original_price or original_price <= 0 or not current_price:
            return None

        discount = ((original_price - current_price) / original_price) * 100
        return round(discount, 1)

    def _get_store_display_name(self, store: str) -> str:
        """Convert store code to display name."""
        store_names = {
            "amazon_us": "Amazon",
            "walmart": "Walmart",
            "bestbuy": "Best Buy",
            "target": "Target",
            "costco": "Costco",
            "newegg": "Newegg",
            "homedepot": "Home Depot",
            "lowes": "Lowe's",
            "macys": "Macy's",
            "microcenter": "Micro Center",
        }
        return store_names.get(store, store.title())

    def _generate_price_ranges(self, min_price: float, max_price: float) -> List[Dict[str, Any]]:
        """Generate dynamic price range facets."""
        if max_price <= min_price:
            return []

        # Create 5 price buckets
        step = (max_price - min_price) / 5
        ranges = []

        for i in range(5):
            range_min = min_price + (i * step)
            range_max = min_price + ((i + 1) * step)
            ranges.append(
                {
                    "min": round(range_min, 2),
                    "max": round(range_max, 2),
                    "count": 0,  # Would need separate query to count
                }
            )

        return ranges
