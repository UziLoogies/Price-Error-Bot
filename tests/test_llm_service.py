"""Tests for LLM service."""

import pytest

from src.ai.llm_service import llm_service


@pytest.mark.asyncio
async def test_call_llm_basic():
    """Test basic LLM call (requires API key)."""
    # Skip if no API key configured
    import os
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OpenAI API key not configured")
    
    prompt = "What is 2+2? Respond with only the number."
    response = await llm_service.call_llm(prompt=prompt)
    
    assert response is not None
    assert len(response) > 0


@pytest.mark.asyncio
async def test_call_llm_structured():
    """Test structured LLM output (requires API key)."""
    import os
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OpenAI API key not configured")
    
    prompt = "Extract the brand from: 'Samsung 55 inch TV'"
    schema = {
        "type": "object",
        "properties": {
            "brand": {"type": "string"},
        },
        "required": ["brand"],
    }
    
    result = await llm_service.call_llm_structured(
        prompt=prompt,
        response_schema=schema,
    )
    
    assert isinstance(result, dict)
    assert "brand" in result


@pytest.mark.asyncio
async def test_llm_cache():
    """Test LLM caching."""
    import os
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OpenAI API key not configured")
    
    prompt = "Test caching prompt"
    
    # First call
    response1 = await llm_service.call_llm(prompt=prompt, use_cache=True)
    
    # Second call - should use cache
    response2 = await llm_service.call_llm(prompt=prompt, use_cache=True)
    
    # Responses should be identical
    assert response1 == response2


@pytest.mark.asyncio
async def test_get_stats():
    """Test getting LLM service statistics."""
    stats = llm_service.get_stats()
    
    assert isinstance(stats, dict)
    assert "call_count" in stats
    assert "daily_cost" in stats
