"""
Tests for search functionality.

Tests the search query builder, service, and API endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from decimal import Decimal

from src.search.query_builder import SearchQueryBuilder
from src.search.service import SearchService
from src.db.models import Product


class TestSearchQueryBuilder:
    """Test the search query builder."""

    def setup_method(self):
        self.builder = SearchQueryBuilder()

    def test_normalize_query(self):
        """Test query normalization."""
        # Basic normalization
        assert self.builder.normalize_query("  hello   world  ") == "hello world"
        assert self.builder.normalize_query("") == ""
        assert self.builder.normalize_query("   ") == ""
        
        # Length limiting
        long_query = "a" * 600
        normalized = self.builder.normalize_query(long_query)
        assert len(normalized) == 500

    def test_tokenize_query(self):
        """Test query tokenization."""
        # Simple terms
        tokens = self.builder.tokenize_query("iphone 13 pro")
        assert tokens['terms'] == ['iphone', '13', 'pro']
        assert tokens['phrases'] == []
        
        # Quoted phrases
        tokens = self.builder.tokenize_query('iphone "13 pro max"')
        assert tokens['terms'] == ['iphone']
        assert tokens['phrases'] == ['13 pro max']
        
        # Field-specific search
        tokens = self.builder.tokenize_query('title:"MacBook Pro" store:amazon')
        assert tokens['field_filters'] == {'title': 'MacBook Pro', 'store': 'amazon'}
        
        # Range queries
        tokens = self.builder.tokenize_query('price:100..500')
        assert tokens['range_filters'] == {'price': {'min': 100.0, 'max': 500.0}}
        
        # Excluded terms
        tokens = self.builder.tokenize_query('iphone -refurbished')
        assert tokens['terms'] == ['iphone']
        assert tokens['exclude_terms'] == ['refurbished']
        
        # Wildcards
        tokens = self.builder.tokenize_query('iphone*')
        assert tokens['has_wildcards'] == True
        assert tokens['terms'] == ['iphone*']

    def test_build_tsquery(self):
        """Test PostgreSQL tsquery generation."""
        # Simple terms
        tokens = {'terms': ['iphone', '13'], 'phrases': [], 'exclude_terms': [], 'boolean_op': 'AND', 'has_wildcards': False}
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "iphone:* & 13:*"
        
        # Phrases
        tokens = {'terms': [], 'phrases': ['iphone 13'], 'exclude_terms': [], 'boolean_op': 'AND', 'has_wildcards': False}
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "'iphone 13'"
        
        # OR operator
        tokens = {'terms': ['iphone', 'samsung'], 'phrases': [], 'exclude_terms': [], 'boolean_op': 'OR', 'has_wildcards': False}
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "iphone:* | samsung:*"
        
        # Excluded terms
        tokens = {'terms': ['iphone'], 'phrases': [], 'exclude_terms': ['refurbished'], 'boolean_op': 'AND', 'has_wildcards': False}
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "iphone:* & !refurbished"

    def test_calculate_query_hash(self):
        """Test query hash generation for caching."""
        hash1 = self.builder.calculate_query_hash(q="iphone", store=["amazon"])
        hash2 = self.builder.calculate_query_hash(q="iphone", store=["amazon"])
        hash3 = self.builder.calculate_query_hash(q="iphone", store=["walmart"])
        
        # Same parameters should generate same hash
        assert hash1 == hash2
        
        # Different parameters should generate different hash
        assert hash1 != hash3
        
        # Hash should be reasonable length
        assert len(hash1) == 16


class TestSearchService:
    """Test the search service."""

    def setup_method(self):
        self.service = SearchService()

    @pytest.mark.asyncio
    async def test_search_products_basic(self):
        """Test basic product search."""
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock query execution result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        
        # Perform search
        result = await self.service.search_products(
            db=mock_db,
            query_text="iphone",
            store=["amazon_us"],
            limit=20
        )
        
        # Verify response structure
        assert 'products' in result
        assert 'pagination' in result
        assert 'facets' in result
        assert 'query_info' in result
        
        # Verify query info
        assert result['query_info']['query'] == 'iphone'
        assert 'response_time_ms' in result['query_info']

    def test_highlight_text(self):
        """Test search term highlighting."""
        highlighted = self.service._highlight_text("iPhone 13 Pro Max", "iphone")
        assert "<mark>iPhone</mark>" in highlighted
        
        highlighted = self.service._highlight_text("B08N5WRWNW", "N5W")
        assert "<mark>N5W</mark>" in highlighted

    def test_calculate_discount_percent(self):
        """Test discount percentage calculation."""
        # Normal discount
        discount = self.service._calculate_discount_percent(Decimal("80.00"), Decimal("100.00"))
        assert discount == 20.0
        
        # No discount
        discount = self.service._calculate_discount_percent(Decimal("100.00"), Decimal("100.00"))
        assert discount == 0.0
        
        # Invalid prices
        discount = self.service._calculate_discount_percent(None, Decimal("100.00"))
        assert discount is None
        
        discount = self.service._calculate_discount_percent(Decimal("80.00"), None)
        assert discount is None

    def test_get_store_display_name(self):
        """Test store code to display name conversion."""
        assert self.service._get_store_display_name("amazon_us") == "Amazon"
        assert self.service._get_store_display_name("bestbuy") == "Best Buy"
        assert self.service._get_store_display_name("unknown_store") == "Unknown_Store"

    def test_generate_price_ranges(self):
        """Test dynamic price range generation."""
        ranges = self.service._generate_price_ranges(0.0, 1000.0)
        
        assert len(ranges) == 5
        assert ranges[0]['min'] == 0.0
        assert ranges[0]['max'] == 200.0
        assert ranges[-1]['max'] == 1000.0
        
        # Each range should have min < max
        for r in ranges:
            if r['min'] != r['max']:  # Allow for edge case
                assert r['min'] < r['max']


@pytest.fixture
def sample_products():
    """Sample products for testing."""
    return [
        Product(
            id=1,
            sku="B08N5WRWNW",
            store="amazon_us",
            title="iPhone 13 Pro 256GB",
            msrp=Decimal("999.99"),
            baseline_price=Decimal("899.99"),
            created_at=datetime.utcnow()
        ),
        Product(
            id=2,
            sku="SKU123456",
            store="walmart",
            title="Samsung Galaxy S21 128GB",
            msrp=Decimal("799.99"),
            baseline_price=Decimal("699.99"),
            created_at=datetime.utcnow()
        )
    ]


class TestSearchIntegration:
    """Integration tests for search functionality."""

    @pytest.mark.asyncio
    async def test_search_query_builder_with_real_data(self, sample_products):
        """Test query builder with realistic product data."""
        builder = SearchQueryBuilder()
        
        # Test product search query building
        query, metadata = builder.build_product_search_query(
            query_text="iphone 13",
            store=["amazon_us"],
            price_min=500.0,
            price_max=1500.0,
            sort_by="relevance",
            limit=20
        )
        
        # Query should be built successfully
        assert query is not None
        assert metadata['uses_fts'] == True
        assert metadata['filter_count'] > 0
        assert metadata['sort_field'] == 'relevance'

    def test_query_validation_edge_cases(self):
        """Test query validation with edge cases."""
        builder = SearchQueryBuilder()
        
        # Empty query
        normalized = builder.normalize_query("")
        assert normalized == ""
        
        # Very long query
        long_query = "search " * 100
        normalized = builder.normalize_query(long_query)
        assert len(normalized) <= 500
        
        # Special characters
        tokens = builder.tokenize_query('product "with quotes" field:value')
        assert 'with quotes' in tokens['phrases']
        assert tokens['field_filters']['field'] == 'value'

    def test_search_performance_considerations(self):
        """Test search features that affect performance."""
        builder = SearchQueryBuilder()
        
        # Test term limit enforcement
        many_terms = " ".join([f"term{i}" for i in range(30)])
        tokens = builder.tokenize_query(many_terms)
        total_terms = len(tokens['terms']) + len(tokens['phrases']) + len(tokens['field_filters'])
        assert total_terms <= 20  # MAX_TERMS limit
        
        # Test query length limit
        very_long_query = "a" * 1000
        normalized = builder.normalize_query(very_long_query)
        assert len(normalized) <= 500  # MAX_QUERY_LENGTH