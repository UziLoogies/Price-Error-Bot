"""
Search query builder with full-text search and filtering support.

Provides functionality to:
- Parse and normalize search queries
- Build PostgreSQL full-text search queries (tsvector/tsquery)
- Add filters and sorting
- Calculate relevance rankings
- Handle pagination with cursors
"""

import re
import hashlib
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from sqlalchemy import select, func, text, or_, and_, desc, asc, case
from sqlalchemy.sql import Select

from src.db.models import Product, Alert, PriceHistory

logger = logging.getLogger(__name__)


class SearchQueryBuilder:
    """Build optimized search queries with full-text search and filtering."""

    # Constants for ranking and limits
    MAX_QUERY_LENGTH = 500
    MAX_TERMS = 20
    MIN_QUERY_LENGTH = 1
    FUZZY_MIN_LENGTH = 3

    # Search term weights for relevance ranking
    EXACT_MATCH_BOOST = 2.0
    PREFIX_MATCH_BOOST = 1.5
    TITLE_WEIGHT = 1.0
    SKU_WEIGHT = 1.2
    STORE_WEIGHT = 0.8
    CONTENT_WEIGHT = 0.6

    def __init__(self):
        self.logger = logger

    def normalize_query(self, query: str) -> str:
        """Normalize search query by trimming and collapsing whitespace."""
        if not query:
            return ""

        # Trim and collapse whitespace
        normalized = re.sub(r"\s+", " ", query.strip())

        # Validate length
        if len(normalized) > self.MAX_QUERY_LENGTH:
            self.logger.warning(f"Query too long, truncating: {len(normalized)} chars")
            normalized = normalized[: self.MAX_QUERY_LENGTH]

        return normalized

    def tokenize_query(self, query: str) -> Dict[str, Any]:
        """
        Parse search query into structured components.

        Supports:
        - Quoted phrases: "iPhone 13 Pro"
        - Field-specific searches: title:"MacBook Pro" store:amazon
        - Boolean operators: AND, OR, NOT (-)
        - Range queries: price:100..500
        - Wildcards: iPhone*

        Returns:
            Dict with parsed query components
        """
        tokens = {
            "terms": [],  # General search terms
            "phrases": [],  # Quoted phrases
            "field_filters": {},  # Field-specific searches (store:amazon)
            "range_filters": {},  # Range queries (price:100..500)
            "exclude_terms": [],  # Excluded terms (-refurbished)
            "boolean_op": "AND",  # Default boolean operator
            "has_wildcards": False,
        }

        # Extract quoted phrases first
        phrase_pattern = r'"([^"]+)"'
        phrases = re.findall(phrase_pattern, query)
        tokens["phrases"] = phrases
        query = re.sub(phrase_pattern, "", query)  # Remove from main query

        # Extract field-specific searches (field:value)
        field_pattern = r"(\w+):([^\s]+)"
        field_matches = re.findall(field_pattern, query)
        for field, value in field_matches:
            if ".." in value:
                # Range query (price:100..500)
                try:
                    min_val, max_val = value.split("..")
                    tokens["range_filters"][field] = {
                        "min": float(min_val) if min_val else None,
                        "max": float(max_val) if max_val else None,
                    }
                except ValueError:
                    self.logger.warning(f"Invalid range filter: {field}:{value}")
            else:
                # Regular field filter
                tokens["field_filters"][field] = value

        query = re.sub(field_pattern, "", query)  # Remove from main query

        # Extract excluded terms (-term)
        exclude_pattern = r"-(\w+)"
        excluded = re.findall(exclude_pattern, query)
        tokens["exclude_terms"] = excluded
        query = re.sub(exclude_pattern, "", query)

        # Check for wildcards
        if "*" in query:
            tokens["has_wildcards"] = True

        # Extract remaining terms
        remaining_terms = query.split()
        tokens["terms"] = [term for term in remaining_terms if term.upper() not in ["AND", "OR"]]

        # Check for boolean operators
        if "OR" in query.upper():
            tokens["boolean_op"] = "OR"

        # Validate term count
        total_terms = len(tokens["terms"]) + len(tokens["phrases"]) + len(tokens["field_filters"])
        if total_terms > self.MAX_TERMS:
            self.logger.warning(
                f"Too many search terms: {total_terms}, limiting to {self.MAX_TERMS}"
            )
            tokens["terms"] = tokens["terms"][: self.MAX_TERMS]

        return tokens

    def build_tsquery(self, tokens: Dict[str, Any]) -> Optional[str]:
        """Build PostgreSQL tsquery from parsed tokens."""
        if not tokens["terms"] and not tokens["phrases"]:
            return None

        query_parts = []

        # Add phrases (exact match)
        for phrase in tokens["phrases"]:
            # Escape and prepare phrase for tsquery
            escaped_phrase = phrase.replace("'", "''")
            query_parts.append(f"'{escaped_phrase}'")

        # Add individual terms
        for term in tokens["terms"]:
            if tokens["has_wildcards"] and "*" in term:
                # Handle prefix matching for wildcards
                clean_term = term.replace("*", ":*")
                query_parts.append(clean_term)
            else:
                # Regular term - add both exact and prefix matching
                query_parts.append(f"{term}:*")

        if not query_parts:
            return None

        # Combine with boolean operator
        operator = " & " if tokens["boolean_op"] == "AND" else " | "
        tsquery = operator.join(query_parts)

        # Add excluded terms
        for exclude in tokens["exclude_terms"]:
            tsquery += f" & !{exclude}"

        return tsquery

    def build_product_search_query(
        self,
        query_text: Optional[str] = None,
        sku: Optional[str] = None,
        title: Optional[str] = None,
        store: Optional[List[str]] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        discount_min: Optional[float] = None,
        has_alerts: Optional[bool] = None,
        in_stock: Optional[bool] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> Tuple[Select, Dict[str, Any]]:
        """
        Build optimized product search query with full-text search and filters.

        Returns:
            Tuple of (SQLAlchemy query, metadata dict)
        """
        # Start with base query
        query = select(Product)

        # Track search metadata
        metadata = {
            "uses_fts": False,
            "uses_trigram": False,
            "filter_count": 0,
            "sort_field": sort_by,
        }

        search_conditions = []

        # Full-text search
        if query_text:
            normalized = self.normalize_query(query_text)
            tokens = self.tokenize_query(normalized)

            if tokens["terms"] or tokens["phrases"]:
                tsquery = self.build_tsquery(tokens)
                if tsquery:
                    # Full-text search with ranking
                    search_conditions.append(Product.search_vector.match(tsquery))
                    metadata["uses_fts"] = True

                    # Add trigram similarity for short queries
                    if len(normalized) >= self.FUZZY_MIN_LENGTH:
                        title_similarity = func.similarity(Product.title, normalized)
                        sku_similarity = func.similarity(Product.sku, normalized)
                        search_conditions.append(or_(title_similarity > 0.3, sku_similarity > 0.3))
                        metadata["uses_trigram"] = True

        # SKU search (exact and partial)
        if sku:
            sku_conditions = [Product.sku.ilike(f"%{sku}%")]
            # Boost exact matches
            if len(sku) >= 6:  # Minimum reasonable SKU length
                sku_conditions.append(Product.sku == sku)
            search_conditions.extend(sku_conditions)
            metadata["filter_count"] += 1

        # Title search
        if title:
            search_conditions.append(Product.title.ilike(f"%{title}%"))
            metadata["filter_count"] += 1

        # Store filter
        if store:
            search_conditions.append(Product.store.in_(store))
            metadata["filter_count"] += 1

        # Price filters
        if price_min is not None:
            price_condition = or_(Product.msrp >= price_min, Product.baseline_price >= price_min)
            search_conditions.append(price_condition)
            metadata["filter_count"] += 1

        if price_max is not None:
            price_condition = or_(Product.msrp <= price_max, Product.baseline_price <= price_max)
            search_conditions.append(price_condition)
            metadata["filter_count"] += 1

        # Date filters
        if created_after:
            search_conditions.append(Product.created_at >= created_after)
            metadata["filter_count"] += 1

        if created_before:
            search_conditions.append(Product.created_at <= created_before)
            metadata["filter_count"] += 1

        # Has alerts filter (requires join)
        if has_alerts is not None:
            from src.db.models import Alert

            if has_alerts:
                query = query.join(Alert, Product.id == Alert.product_id)
            else:
                query = query.outerjoin(Alert, Product.id == Alert.product_id)
                search_conditions.append(Alert.id.is_(None))
            metadata["filter_count"] += 1

        # In stock filter (requires subquery to latest price history)
        if in_stock is not None:
            latest_price_subq = (
                select(PriceHistory.product_id, PriceHistory.availability)
                .distinct(PriceHistory.product_id)
                .order_by(PriceHistory.product_id, PriceHistory.fetched_at.desc())
                .subquery()
            )
            query = query.join(latest_price_subq, Product.id == latest_price_subq.c.product_id)

            if in_stock:
                search_conditions.append(
                    latest_price_subq.c.availability.in_(["In Stock", "Limited Stock"])
                )
            else:
                search_conditions.append(latest_price_subq.c.availability.in_(["Out of Stock"]))
            metadata["filter_count"] += 1

        # Apply all conditions
        if search_conditions:
            if len(search_conditions) == 1:
                query = query.where(search_conditions[0])
            else:
                query = query.where(and_(*search_conditions))

        # Add sorting
        if sort_by == "relevance" and metadata["uses_fts"]:
            # Use ts_rank for relevance sorting
            rank_expr = func.ts_rank(Product.search_vector, text(f"'{tsquery}'"))
            query = query.add_columns(rank_expr.label("search_rank"))
            if sort_order == "desc":
                query = query.order_by(desc("search_rank"), desc(Product.created_at))
            else:
                query = query.order_by(asc("search_rank"), asc(Product.created_at))
        else:
            # Standard sorting
            sort_field = getattr(Product, sort_by, Product.created_at)
            if sort_order == "desc":
                query = query.order_by(desc(sort_field))
            else:
                query = query.order_by(asc(sort_field))

        # Add deterministic ordering for pagination
        query = query.order_by(Product.id)

        # Apply limit
        query = query.limit(limit + 1)  # +1 to check for next page

        return query, metadata

    def build_alert_search_query(
        self,
        query_text: Optional[str] = None,
        store: Optional[List[str]] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        discount_min: Optional[float] = None,
        discount_max: Optional[float] = None,
        rule_type: Optional[List[str]] = None,
        sent_after: Optional[datetime] = None,
        sent_before: Optional[datetime] = None,
        has_message_id: Optional[bool] = None,
        sort_by: str = "sent_at",
        sort_order: str = "desc",
        limit: int = 20,
    ) -> Tuple[Select, Dict[str, Any]]:
        """Build alert search query with product joins."""

        # Join with product for search capabilities
        query = select(Alert).join(Product, Alert.product_id == Product.id)

        metadata = {"uses_fts": False, "filter_count": 0, "sort_field": sort_by}

        search_conditions = []

        # Text search in product title/SKU
        if query_text:
            normalized = self.normalize_query(query_text)
            tokens = self.tokenize_query(normalized)

            if tokens["terms"] or tokens["phrases"]:
                # Search in product fields
                text_conditions = [
                    Product.title.ilike(f"%{normalized}%"),
                    Product.sku.ilike(f"%{normalized}%"),
                ]
                search_conditions.append(or_(*text_conditions))

        # Store filter (via product)
        if store:
            search_conditions.append(Product.store.in_(store))
            metadata["filter_count"] += 1

        # Price filters
        if price_min is not None:
            search_conditions.append(Alert.triggered_price >= price_min)
            metadata["filter_count"] += 1

        if price_max is not None:
            search_conditions.append(Alert.triggered_price <= price_max)
            metadata["filter_count"] += 1

        # Discount filters (calculated on the fly)
        if discount_min is not None or discount_max is not None:
            discount_expr = case(
                (
                    Alert.previous_price > 0,
                    ((Alert.previous_price - Alert.triggered_price) / Alert.previous_price * 100),
                ),
                else_=0,
            )

            if discount_min is not None:
                search_conditions.append(discount_expr >= discount_min)
                metadata["filter_count"] += 1

            if discount_max is not None:
                search_conditions.append(discount_expr <= discount_max)
                metadata["filter_count"] += 1

        # Date filters
        if sent_after:
            search_conditions.append(Alert.sent_at >= sent_after)
            metadata["filter_count"] += 1

        if sent_before:
            search_conditions.append(Alert.sent_at <= sent_before)
            metadata["filter_count"] += 1

        # Message ID filter
        if has_message_id is not None:
            if has_message_id:
                search_conditions.append(Alert.discord_message_id.isnot(None))
            else:
                search_conditions.append(Alert.discord_message_id.is_(None))
            metadata["filter_count"] += 1

        # Apply conditions
        if search_conditions:
            query = query.where(and_(*search_conditions))

        # Add sorting
        sort_field = getattr(Alert, sort_by, Alert.sent_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_field))
        else:
            query = query.order_by(asc(sort_field))

        # Deterministic ordering
        query = query.order_by(Alert.id)
        query = query.limit(limit + 1)

        return query, metadata

    def calculate_query_hash(self, **params) -> str:
        """Generate cache key from search parameters."""
        # Filter out None values and normalize
        clean_params = {k: v for k, v in params.items() if v is not None}

        # Convert to deterministic string
        param_str = str(sorted(clean_params.items()))

        # Generate hash
        return hashlib.md5(param_str.encode()).hexdigest()[:16]
