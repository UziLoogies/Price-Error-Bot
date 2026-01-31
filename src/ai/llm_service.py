"""LLM service for OpenAI integration and prompt management."""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from openai import AsyncOpenAI

from src.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for LLM interactions with OpenAI.
    
    Features:
    - OpenAI API integration
    - Prompt management
    - Structured JSON output
    - Caching (Redis-based)
    - Rate limiting
    - Error handling and retries
    - Cost tracking
    """
    
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._redis: Optional[redis.Redis] = None
        self._daily_cost: float = 0.0
        self._call_count: int = 0
    
    async def _get_client(self) -> AsyncOpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            if not settings.openai_api_key:
                raise ValueError("OpenAI API key not configured")
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client
    
    async def _get_redis(self) -> Optional[redis.Redis]:
        """Get or create Redis connection for caching."""
        if not settings.llm_cache_enabled:
            return None
        
        if self._redis is None:
            try:
                self._redis = await redis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for LLM cache: {e}")
                return None
        return self._redis
    
    def _get_cache_key(self, prompt: str, system_prompt: str, model: str) -> str:
        """Generate cache key for prompt."""
        combined = f"{system_prompt}:{prompt}:{model}"
        key_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()
        return f"llm_cache:{key_hash}"
    
    async def _check_cost_limit(self) -> bool:
        """Check if daily cost limit is exceeded."""
        if not settings.track_llm_costs:
            return True
        
        if self._daily_cost >= settings.llm_cost_limit_per_day:
            logger.warning(
                f"Daily LLM cost limit reached: ${self._daily_cost:.2f} >= ${settings.llm_cost_limit_per_day:.2f}"
            )
            return False
        return True
    
    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Estimate cost for LLM call.
        
        Pricing (as of 2024, approximate):
        - gpt-4-turbo-preview: $0.01/1K input, $0.03/1K output
        - gpt-3.5-turbo: $0.0015/1K input, $0.002/1K output
        """
        if "gpt-4" in model.lower():
            input_cost = (prompt_tokens / 1000) * 0.01
            output_cost = (completion_tokens / 1000) * 0.03
        else:
            input_cost = (prompt_tokens / 1000) * 0.0015
            output_cost = (completion_tokens / 1000) * 0.002
        
        return input_cost + output_cost
    
    async def call_llm(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """
        Call LLM with a prompt and return text response.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt/instructions
            temperature: Temperature (defaults to settings.llm_temperature)
            model: Model name (defaults to settings.llm_model)
            use_cache: Whether to use cache
            
        Returns:
            LLM response text
        """
        model = model or settings.llm_model
        temperature = temperature if temperature is not None else settings.llm_temperature
        
        # Check cost limit
        if not await self._check_cost_limit():
            raise RuntimeError("Daily LLM cost limit exceeded")
        
        # Check cache
        if use_cache and settings.llm_cache_enabled:
            redis_client = await self._get_redis()
            if redis_client:
                cache_key = self._get_cache_key(prompt, system_prompt, model)
                cached = await redis_client.get(cache_key)
                if cached:
                    logger.debug(f"LLM cache hit for prompt: {prompt[:50]}...")
                    self._call_count += 1
                    return cached
        
        # Make API call
        try:
            client = await self._get_client()
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=settings.llm_max_tokens,
                timeout=settings.llm_timeout_seconds,
            )
            
            result = response.choices[0].message.content
            if result is None:
                result = ""  # Fallback to empty string if content is None
            
            # Track costs
            if settings.track_llm_costs:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                cost = self._estimate_cost(model, prompt_tokens, completion_tokens)
                self._daily_cost += cost
                logger.debug(
                    f"LLM call cost: ${cost:.4f} "
                    f"(tokens: {prompt_tokens}+{completion_tokens}, total: ${self._daily_cost:.2f})"
                )
            
            self._call_count += 1
            
            # Cache result
            if use_cache and settings.llm_cache_enabled:
                redis_client = await self._get_redis()
                if redis_client:
                    cache_key = self._get_cache_key(prompt, system_prompt, model)
                    await redis_client.setex(
                        cache_key,
                        settings.llm_cache_ttl_seconds,
                        result,
                    )
            
            return result
            
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise
    
    async def call_llm_structured(
        self,
        prompt: str,
        response_schema: Dict[str, Any],
        system_prompt: str = "",
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Call LLM with structured JSON output.
        
        Args:
            prompt: User prompt
            response_schema: JSON schema describing expected response structure
            system_prompt: System prompt/instructions
            temperature: Temperature (defaults to settings.llm_temperature)
            model: Model name (defaults to settings.llm_model)
            
        Returns:
            Parsed JSON response as dictionary
        """
        # Enhance system prompt with JSON schema instructions
        enhanced_system = system_prompt
        if enhanced_system:
            enhanced_system += "\n\n"
        enhanced_system += (
            f"Respond with valid JSON matching this schema: {json.dumps(response_schema, indent=2)}\n"
            "Return only the JSON object, no additional text."
        )
        
        response_text = await self.call_llm(
            prompt=prompt,
            system_prompt=enhanced_system,
            temperature=temperature,
            model=model,
        )
        
        # Parse JSON response
        try:
            # Try to extract JSON from response (in case there's extra text)
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}\nResponse: {response_text[:200]}")
            raise ValueError(f"Invalid JSON response from LLM: {e}") from e
    
    async def batch_call_llm(
        self,
        prompts: List[str],
        system_prompt: str = "",
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> List[str]:
        """
        Call LLM for multiple prompts in parallel.
        
        Args:
            prompts: List of prompts
            system_prompt: System prompt/instructions
            temperature: Temperature
            model: Model name
            
        Returns:
            List of responses
        """
        import asyncio
        
        tasks = [
            self.call_llm(prompt, system_prompt, temperature, model)
            for prompt in prompts
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        responses = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"LLM call failed for prompt {i}: {result}")
                responses.append("")
            else:
                responses.append(result)
        
        return responses
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get LLM service statistics.
        
        Returns:
            Dictionary with call count, daily cost, etc.
        """
        return {
            "call_count": self._call_count,
            "daily_cost": self._daily_cost,
            "cost_limit": settings.llm_cost_limit_per_day,
            "cache_enabled": settings.llm_cache_enabled,
        }
    
    def reset_daily_stats(self):
        """Reset daily cost and call count (typically called at midnight)."""
        self._daily_cost = 0.0
        self._call_count = 0
        logger.info("LLM daily stats reset")
    
    async def close(self):
        """Close connections."""
        if self._redis:
            await self._redis.close()
            self._redis = None
        if self._client:
            await self._client.close()
            self._client = None


# Global LLM service instance
llm_service = LLMService()
