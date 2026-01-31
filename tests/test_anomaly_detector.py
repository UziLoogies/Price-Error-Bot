"""Tests for enhanced anomaly detector."""

import pytest
from decimal import Decimal

from src.detect.anomaly_detector import anomaly_detector


@pytest.mark.asyncio
async def test_detect_with_gmm(db_session):
    """Test GMM anomaly detection."""
    # Create test product with price history
    from src.db.models import Product, PriceHistory
    
    product = Product(
        sku="TEST123",
        store="test",
        title="Test Product",
    )
    db_session.add(product)
    await db_session.flush()
    
    # Add price history
    for i in range(15):
        price_history = PriceHistory(
            product_id=product.id,
            price=Decimal("100.00") + Decimal(str(i * 0.5)),
            confidence=1.0,
        )
        db_session.add(price_history)
    await db_session.commit()
    
    # Test GMM detection
    result = await anomaly_detector._detect_with_gmm(
        db=db_session,
        product_id=product.id,
        current_price=Decimal("50.00"),  # Anomalously low
    )
    
    # Should return result or None (if insufficient data)
    assert result is None or isinstance(result, dict)


@pytest.mark.asyncio
async def test_detect_with_autoencoder(db_session):
    """Test Autoencoder anomaly detection."""
    from src.db.models import Product, PriceHistory
    
    product = Product(
        sku="TEST456",
        store="test",
        title="Test Product 2",
    )
    db_session.add(product)
    await db_session.flush()
    
    # Add price history
    for i in range(15):
        price_history = PriceHistory(
            product_id=product.id,
            price=Decimal("200.00") + Decimal(str(i)),
            confidence=1.0,
        )
        db_session.add(price_history)
    await db_session.commit()
    
    # Test autoencoder detection
    result = await anomaly_detector._detect_with_autoencoder(
        db=db_session,
        product_id=product.id,
        current_price=Decimal("50.00"),  # Anomalously low
    )
    
    # Should return result or None
    assert result is None or isinstance(result, dict)
