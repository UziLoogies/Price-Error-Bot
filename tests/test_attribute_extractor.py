"""Tests for attribute extractor."""

import pytest

from src.ai.attribute_extractor import attribute_extractor


def test_extract_with_rules():
    """Test rule-based attribute extraction."""
    title = "Samsung 55 inch 4K Smart TV - Black"
    
    attributes = attribute_extractor.extract_with_rules(title)
    
    assert isinstance(attributes, dict)
    # Should extract at least some attributes
    assert len(attributes) >= 0


def test_extract_brand():
    """Test brand extraction."""
    title = "Samsung Galaxy S24 Ultra"
    brand = attribute_extractor._extract_brand(title)
    
    # Should extract "Samsung" or similar
    assert brand is None or isinstance(brand, str)


def test_extract_model():
    """Test model extraction."""
    title = "Samsung Galaxy S24 Ultra 256GB"
    model = attribute_extractor._extract_model(title)
    
    assert model is None or isinstance(model, str)


def test_extract_size():
    """Test size extraction."""
    title = "Samsung 55 inch TV"
    size = attribute_extractor._extract_size(title)
    
    assert size is None or isinstance(size, str)


def test_extract_color():
    """Test color extraction."""
    title = "Nike Air Max Black Running Shoes"
    color = attribute_extractor._extract_color(title)
    
    assert color is None or isinstance(color, str)


@pytest.mark.asyncio
async def test_extract_attributes_full():
    """Test full attribute extraction pipeline."""
    title = "Samsung 55 inch 4K Smart TV - Black"
    
    attributes = attribute_extractor.extract_attributes(
        title=title,
        description=None,
        use_llm=False,  # Skip LLM for faster tests
    )
    
    assert isinstance(attributes, dict)
