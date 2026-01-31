"""Tests for product matcher."""

import pytest
from decimal import Decimal

from src.ai.product_matcher import product_matcher
from src.db.models import Product


@pytest.mark.asyncio
async def test_generate_product_embedding(db_session):
    """Test generating embedding for a product."""
    product = Product(
        sku="TEST123",
        store="test_store",
        title="Samsung 55 inch 4K Smart TV",
    )
    
    embedding = await product_matcher.generate_product_embedding(product)
    
    assert embedding is not None
    assert len(embedding) > 0


@pytest.mark.asyncio
async def test_find_similar_products(db_session):
    """Test finding similar products."""
    # Create test products
    product1 = Product(
        sku="PROD1",
        store="store1",
        title="Samsung 55 inch 4K Smart TV",
        baseline_price=Decimal("499.99"),
    )
    db_session.add(product1)
    await db_session.commit()
    
    # Find similar products (may be empty if no matches)
    matches = await product_matcher.find_similar_products(
        db=db_session,
        product=product1,
        threshold=0.85,
        limit=10,
    )
    
    assert isinstance(matches, list)


@pytest.mark.asyncio
async def test_batch_update_embeddings(db_session):
    """Test batch updating embeddings."""
    products = [
        Product(sku=f"SKU{i}", store="test", title=f"Product {i}")
        for i in range(5)
    ]
    
    for p in products:
        db_session.add(p)
    await db_session.commit()
    
    # Batch update embeddings
    await product_matcher.batch_update_embeddings(
        db=db_session,
        products=products,
    )
    
    # Should complete without error
    assert True
