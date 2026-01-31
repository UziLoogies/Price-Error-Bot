"""Tests for embedding service."""

import numpy as np
import pytest

from src.ai.embedding_service import embedding_service


@pytest.mark.asyncio
async def test_generate_embedding():
    """Test single embedding generation."""
    text = "Samsung 55 inch 4K Smart TV"
    embedding = embedding_service.generate_embedding(text)
    
    assert embedding is not None
    assert isinstance(embedding, np.ndarray)
    assert len(embedding) > 0
    assert embedding.dtype == np.float32 or embedding.dtype == np.float64


@pytest.mark.asyncio
async def test_generate_embeddings_batch():
    """Test batch embedding generation."""
    texts = [
        "Samsung 55 inch 4K Smart TV",
        "Apple iPhone 15 Pro Max",
        "Nike Air Max Running Shoes",
    ]
    
    embeddings = embedding_service.generate_embeddings_batch(texts)
    
    assert len(embeddings) == len(texts)
    assert all(isinstance(e, np.ndarray) for e in embeddings)
    assert all(len(e) > 0 for e in embeddings)


@pytest.mark.asyncio
async def test_embedding_cache():
    """Test embedding caching."""
    text = "Test product for caching"
    
    # First call - should miss cache
    embedding1 = embedding_service.generate_embedding(text, use_cache=True)
    
    # Second call - should hit cache
    embedding2 = embedding_service.generate_embedding(text, use_cache=True)
    
    # Embeddings should be identical
    np.testing.assert_array_equal(embedding1, embedding2)


@pytest.mark.asyncio
async def test_get_embedding_dimension():
    """Test getting embedding dimension."""
    dim = embedding_service.get_embedding_dimension()
    assert dim > 0
    assert isinstance(dim, int)
