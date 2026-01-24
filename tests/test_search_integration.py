"""
Integration tests for search functionality.

Tests the complete search pipeline with real database operations:
- API endpoints with test data
- Database query performance 
- Search result accuracy
- Pagination and filtering
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from src.main import app
from src.db.models import Base, Product, Alert, Rule, StoreCategory, PriceHistory
from src.api.deps import get_database

# Test database configuration
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_search.db"

# Create test engine and session
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestAsyncSession = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture
async def test_db():
    """Create test database with tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session = TestAsyncSession()
    try:
        yield session
    finally:
        await session.close()
    
    # Clean up
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
def client(test_db):
    """Create test client with database override."""
    async def get_test_database():
        yield test_db
    
    app.dependency_overrides[get_database] = get_test_database
    
    with TestClient(app) as test_client:
        yield test_client
    
    # Clean up
    app.dependency_overrides.clear()

@pytest.fixture
async def sample_products(test_db: AsyncSession) -> List[Product]:
    """Create sample products for testing."""
    products = [
        Product(
            sku="B08N5WRWNW",
            store="amazon_us",
            title="Apple iPhone 13 Pro 256GB - Sierra Blue",
            url="https://amazon.com/dp/B08N5WRWNW",
            msrp=Decimal("999.99"),
            baseline_price=Decimal("899.99"),
            created_at=datetime.utcnow()
        ),
        Product(
            sku="123456789",
            store="walmart",
            title="Samsung Galaxy S21 128GB Phantom Black",
            url="https://walmart.com/ip/123456789",
            msrp=Decimal("799.99"),
            baseline_price=Decimal("699.99"),
            created_at=datetime.utcnow() - timedelta(days=1)
        ),
        Product(
            sku="6456789",
            store="bestbuy",
            title="Dell XPS 13 Laptop Intel Core i7 512GB",
            url="https://bestbuy.com/site/6456789",
            msrp=Decimal("1299.99"),
            baseline_price=Decimal("1199.99"),
            created_at=datetime.utcnow() - timedelta(days=2)
        ),
        Product(
            sku="B084DWCZK1",
            store="amazon_us",
            title="Sony WH-1000XM4 Wireless Headphones Black",
            url="https://amazon.com/dp/B084DWCZK1",
            msrp=Decimal("349.99"),
            baseline_price=Decimal("299.99"),
            created_at=datetime.utcnow() - timedelta(days=3)
        ),
        Product(
            sku="555123456",
            store="target",
            title="Nintendo Switch OLED Model White",
            url="https://target.com/p/555123456",
            msrp=Decimal("349.99"),
            baseline_price=Decimal("349.99"),
            created_at=datetime.utcnow() - timedelta(days=4)
        )
    ]
    
    for product in products:
        test_db.add(product)
    
    await test_db.commit()
    
    # Refresh to get IDs
    for product in products:
        await test_db.refresh(product)
    
    return products

@pytest.fixture 
async def sample_price_history(test_db: AsyncSession, sample_products: List[Product]):
    """Create sample price history for testing."""
    history_records = []
    
    for product in sample_products[:3]:  # Add history for first 3 products
        # Create 3-5 price points
        for i in range(3):
            price = product.baseline_price * Decimal(str(0.8 + (i * 0.1)))
            availability = ["In Stock", "Limited Stock", "Out of Stock"][i % 3]
            
            history = PriceHistory(
                product_id=product.id,
                price=price,
                original_price=price * Decimal("1.2"),
                shipping=Decimal("0.00"),
                availability=availability,
                confidence=0.95,
                fetched_at=datetime.utcnow() - timedelta(hours=i * 6)
            )
            
            history_records.append(history)
            test_db.add(history)
    
    await test_db.commit()
    return history_records

@pytest.fixture
async def sample_alerts(test_db: AsyncSession, sample_products: List[Product]):
    """Create sample alerts for testing."""
    # First create a rule
    rule = Rule(
        name="Test Rule",
        rule_type="percentage",
        threshold=Decimal("50.0"),
        enabled=True,
        priority=1
    )
    test_db.add(rule)
    await test_db.commit()
    await test_db.refresh(rule)
    
    alerts = []
    for product in sample_products[:2]:  # Add alerts for first 2 products
        alert = Alert(
            product_id=product.id,
            rule_id=rule.id,
            triggered_price=product.baseline_price * Decimal("0.6"),
            previous_price=product.baseline_price,
            discord_message_id="msg_123456",
            sent_at=datetime.utcnow() - timedelta(hours=1)
        )
        
        alerts.append(alert)
        test_db.add(alert)
    
    await test_db.commit()
    return alerts


class TestSearchQueryBuilder:
    """Test search query builder functionality."""

    def setup_method(self):
        self.builder = SearchQueryBuilder()

    def test_query_normalization(self):
        """Test various query normalization scenarios."""
        # Basic cases
        assert self.builder.normalize_query("  hello   world  ") == "hello world"
        assert self.builder.normalize_query("") == ""
        assert self.builder.normalize_query("   ") == ""
        
        # Special characters
        assert self.builder.normalize_query("iPhone-13 Pro!") == "iPhone-13 Pro!"
        
        # Length limiting
        long_query = "search term " * 100
        normalized = self.builder.normalize_query(long_query)
        assert len(normalized) <= 500

    def test_query_tokenization_advanced(self):
        """Test advanced query parsing scenarios."""
        # Complex query with multiple features
        query = 'iphone "13 pro" store:amazon price:500..1000 -refurbished OR samsung'
        tokens = self.builder.tokenize_query(query)
        
        assert 'iphone' in tokens['terms'] or 'samsung' in tokens['terms']
        assert '13 pro' in tokens['phrases']
        assert tokens['field_filters']['store'] == 'amazon'
        assert tokens['range_filters']['price'] == {'min': 500.0, 'max': 1000.0}
        assert 'refurbished' in tokens['exclude_terms']
        assert tokens['boolean_op'] == 'OR'

    def test_tsquery_generation(self):
        """Test PostgreSQL tsquery generation."""
        # Simple case
        tokens = {
            'terms': ['iphone', '13'],
            'phrases': [],
            'exclude_terms': [],
            'boolean_op': 'AND',
            'has_wildcards': False
        }
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "iphone:* & 13:*"
        
        # With phrases and exclusions
        tokens = {
            'terms': ['apple'],
            'phrases': ['13 pro'],
            'exclude_terms': ['refurbished'],
            'boolean_op': 'AND',
            'has_wildcards': False
        }
        tsquery = self.builder.build_tsquery(tokens)
        assert tsquery == "'13 pro' & apple:* & !refurbished"


class TestSearchAPI:
    """Test search API endpoints."""

    @pytest.mark.asyncio
    async def test_product_search_endpoint(self, client: TestClient, sample_products):
        """Test product search API endpoint."""
        # Basic search
        response = client.get("/api/search/products?q=iphone")
        assert response.status_code == 200
        
        data = response.json()
        assert 'products' in data
        assert 'pagination' in data
        assert 'facets' in data
        assert 'query_info' in data
        
        # Should find iPhone products
        products = data['products']
        assert len(products) > 0
        
        # Check response structure
        if products:
            product = products[0]
            required_fields = ['id', 'sku', 'store', 'title', 'search_score', 'created_at']
            for field in required_fields:
                assert field in product

    @pytest.mark.asyncio  
    async def test_product_search_with_filters(self, client: TestClient, sample_products):
        """Test product search with various filters."""
        # Search with store filter
        response = client.get("/api/search/products?q=phone&stores=amazon_us")
        assert response.status_code == 200
        
        data = response.json()
        if data['products']:
            # All results should be from Amazon
            for product in data['products']:
                assert product['store'] == 'amazon_us'

    @pytest.mark.asyncio
    async def test_product_search_price_filters(self, client: TestClient, sample_products):
        """Test price range filtering."""
        # Search with price range
        response = client.get("/api/search/products?q=&price_min=500&price_max=1000")
        assert response.status_code == 200
        
        data = response.json()
        for product in data['products']:
            price = product.get('msrp') or product.get('baseline_price')
            if price:
                assert 500 <= price <= 1000

    @pytest.mark.asyncio
    async def test_product_search_sorting(self, client: TestClient, sample_products):
        """Test different sorting options."""
        # Sort by price ascending
        response = client.get("/api/search/products?q=&sort_by=msrp&sort_order=asc")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        if len(products) > 1:
            # Verify ascending order (where prices exist)
            prices = [p.get('msrp') for p in products if p.get('msrp')]
            if len(prices) > 1:
                assert prices == sorted(prices)

    @pytest.mark.asyncio
    async def test_search_suggestions(self, client: TestClient, sample_products):
        """Test search suggestions endpoint."""
        response = client.get("/api/search/suggestions?q=iph&entity_type=products")
        assert response.status_code == 200
        
        data = response.json()
        assert 'suggestions' in data
        assert 'recent_searches' in data
        assert 'popular_searches' in data
        
        # Should provide suggestions for partial "iph" -> "iPhone"
        suggestions = data['suggestions']
        assert isinstance(suggestions, list)

    @pytest.mark.asyncio
    async def test_alert_search_endpoint(self, client: TestClient, sample_alerts):
        """Test alert search API endpoint."""
        response = client.get("/api/search/alerts?q=")
        assert response.status_code == 200
        
        data = response.json()
        assert 'alerts' in data
        assert 'pagination' in data
        assert 'facets' in data

    @pytest.mark.asyncio
    async def test_search_error_handling(self, client: TestClient):
        """Test search error handling."""
        # Query too long
        long_query = "a" * 600
        response = client.get(f"/api/search/products?q={long_query}")
        assert response.status_code == 400
        
        error_data = response.json()
        assert 'detail' in error_data
        assert 'too long' in error_data['detail'].lower()

    @pytest.mark.asyncio
    async def test_search_parameter_validation(self, client: TestClient):
        """Test parameter validation."""
        # Invalid price range
        response = client.get("/api/search/products?price_min=1000&price_max=500")
        # Should still work (backend handles it gracefully)
        assert response.status_code in [200, 400]
        
        # Invalid limit
        response = client.get("/api/search/products?limit=200")
        assert response.status_code == 422  # Validation error


class TestSearchPerformance:
    """Test search performance characteristics."""

    @pytest.mark.asyncio
    async def test_search_response_time(self, client: TestClient, sample_products, sample_price_history):
        """Test search response time meets targets."""
        import time
        
        # Simple search should be fast
        start_time = time.time()
        response = client.get("/api/search/products?q=iphone")
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 1.0  # Should be under 1 second for simple search
        
        # Complex filtered search
        start_time = time.time()
        response = client.get("/api/search/products?q=phone&stores=amazon_us&price_min=300&price_max=1200&sort_by=relevance")
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 2.0  # Should be under 2 seconds for complex search

    @pytest.mark.asyncio
    async def test_large_result_set_performance(self, client: TestClient, test_db: AsyncSession):
        """Test performance with larger datasets."""
        # Create more products for testing
        products = []
        for i in range(100):
            product = Product(
                sku=f"TEST_SKU_{i:04d}",
                store=["amazon_us", "walmart", "bestbuy"][i % 3],
                title=f"Test Product {i} - Electronics Category",
                msrp=Decimal(str(50 + i * 10)),
                baseline_price=Decimal(str(45 + i * 9)),
                created_at=datetime.utcnow() - timedelta(days=i // 10)
            )
            products.append(product)
            test_db.add(product)
        
        await test_db.commit()
        
        # Test search performance
        import time
        start_time = time.time()
        response = client.get("/api/search/products?q=electronics")
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 1.5  # Should handle 100+ products efficiently
        
        data = response.json()
        assert len(data['products']) > 0

    @pytest.mark.asyncio
    async def test_concurrent_search_requests(self, client: TestClient, sample_products):
        """Test handling of concurrent search requests."""
        import asyncio
        import aiohttp
        
        async def make_request(session, query):
            async with session.get(f"http://testserver/api/search/products?q={query}") as response:
                return await response.json()
        
        # Note: This test would need real async client
        # For now, just test that sequential requests work
        responses = []
        queries = ["iphone", "samsung", "dell", "sony", "nintendo"]
        
        for query in queries:
            response = client.get(f"/api/search/products?q={query}")
            assert response.status_code == 200
            responses.append(response.json())
        
        # All requests should succeed
        assert len(responses) == len(queries)
        for response_data in responses:
            assert 'products' in response_data

class TestSearchAccuracy:
    """Test search result accuracy and relevance."""

    @pytest.mark.asyncio
    async def test_exact_match_priority(self, client: TestClient, sample_products):
        """Test that exact matches get highest priority."""
        # Search for exact SKU
        response = client.get("/api/search/products?q=B08N5WRWNW")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        if products:
            # First result should be the exact SKU match
            assert products[0]['sku'] == 'B08N5WRWNW'
            
            # Should have high search score
            if products[0].get('search_score'):
                assert products[0]['search_score'] > 0.5

    @pytest.mark.asyncio
    async def test_partial_title_matching(self, client: TestClient, sample_products):
        """Test partial title matching."""
        response = client.get("/api/search/products?q=iPhone Pro")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        # Should find iPhone products
        iphone_found = any('iPhone' in product.get('title', '') for product in products)
        assert iphone_found

    @pytest.mark.asyncio
    async def test_store_filtering_accuracy(self, client: TestClient, sample_products):
        """Test store filtering is applied correctly."""
        response = client.get("/api/search/products?stores=amazon_us")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        # All results should be from Amazon
        for product in products:
            assert product['store'] == 'amazon_us'

    @pytest.mark.asyncio
    async def test_price_range_accuracy(self, client: TestClient, sample_products):
        """Test price range filtering accuracy."""
        response = client.get("/api/search/products?price_min=300&price_max=800")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        for product in products:
            # Check MSRP or baseline_price is in range
            price = product.get('msrp') or product.get('baseline_price')
            if price:
                assert 300 <= price <= 800, f"Product {product['sku']} price {price} not in range 300-800"

    @pytest.mark.asyncio
    async def test_search_highlighting(self, client: TestClient, sample_products):
        """Test search term highlighting in results."""
        response = client.get("/api/search/products?q=iPhone")
        assert response.status_code == 200
        
        data = response.json()
        products = data['products']
        
        for product in products:
            highlights = product.get('highlights', {})
            
            # If product title contains "iPhone", it should be highlighted
            if product.get('title') and 'iPhone' in product['title']:
                if 'title' in highlights:
                    assert '<mark>' in highlights['title'][0]
                    assert '</mark>' in highlights['title'][0]

    @pytest.mark.asyncio
    async def test_empty_search_handling(self, client: TestClient):
        """Test handling of empty or no-result searches."""
        # Empty query
        response = client.get("/api/search/products?q=")
        assert response.status_code == 422  # Validation should require min_length
        
        # Query with no results
        response = client.get("/api/search/products?q=zyxwvutsrqponmlkjihgfedcba")
        assert response.status_code == 200
        
        data = response.json()
        assert data['products'] == []
        assert data['query_info']['total_results'] == 0


class TestSearchFacets:
    """Test faceted search functionality."""

    @pytest.mark.asyncio
    async def test_store_facets(self, client: TestClient, sample_products):
        """Test store facet generation."""
        response = client.get("/api/search/products?q=")
        assert response.status_code == 422  # Would need to adjust for empty query
        
        # Test with actual query
        response = client.get("/api/search/products?q=test")
        assert response.status_code == 200
        
        data = response.json()
        facets = data.get('facets', {})
        
        if 'stores' in facets:
            stores = facets['stores']
            assert isinstance(stores, list)
            
            for store in stores:
                assert 'name' in store
                assert 'count' in store
                assert isinstance(store['count'], int)

    @pytest.mark.asyncio
    async def test_price_range_facets(self, client: TestClient, sample_products):
        """Test price range facet generation."""
        response = client.get("/api/search/products?q=product")
        assert response.status_code == 200
        
        data = response.json()
        facets = data.get('facets', {})
        
        if 'price_ranges' in facets:
            ranges = facets['price_ranges']
            assert isinstance(ranges, list)
            
            for range_item in ranges:
                assert 'min' in range_item
                assert 'max' in range_item
                assert 'count' in range_item


@pytest.mark.asyncio  
async def test_search_end_to_end_flow(client: TestClient, sample_products, sample_price_history, sample_alerts):
    """Test complete end-to-end search workflow."""
    # 1. Search for products
    search_response = client.get("/api/search/products?q=iPhone&limit=10")
    assert search_response.status_code == 200
    
    search_data = search_response.json()
    assert len(search_data['products']) > 0
    
    # 2. Get suggestions
    suggestions_response = client.get("/api/search/suggestions?q=iPh&entity_type=products")
    assert suggestions_response.status_code == 200
    
    suggestions_data = suggestions_response.json()
    assert 'suggestions' in suggestions_data
    
    # 3. Search alerts  
    alerts_response = client.get("/api/search/alerts?q=iPhone")
    assert alerts_response.status_code == 200
    
    alerts_data = alerts_response.json()
    assert 'alerts' in alerts_data
    
    # End-to-end success
    print(f"✅ End-to-end test completed:")
    print(f"   - Found {len(search_data['products'])} products")
    print(f"   - Got {len(suggestions_data['suggestions'])} suggestions")
    print(f"   - Found {len(alerts_data['alerts'])} alerts")