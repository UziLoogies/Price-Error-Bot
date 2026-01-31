"""LLM-based anomaly reviewer for validating and explaining price anomalies."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.llm_service import llm_service
from src.config import settings
from src.db.models import Product, PriceHistory
from src.detect.anomaly_detector import AnomalyResult

logger = logging.getLogger(__name__)


@dataclass
class LLMReview:
    """Result of LLM review."""
    
    is_valid: bool
    confidence_adjustment: float  # Adjustment to add/subtract from confidence
    explanation: str
    suggested_features: List[str]
    edge_case_notes: Optional[str] = None


class LLMAnomalyReviewer:
    """
    LLM-based reviewer for anomaly detection results.
    
    Features:
    - Review ML model outputs
    - Generate human-readable explanations
    - Validate edge cases
    - Suggest missing features
    - Provide confidence adjustments
    """
    
    async def review_anomaly(
        self,
        product: Product,
        current_price: Decimal,
        ml_result: AnomalyResult,
        db: AsyncSession,
    ) -> LLMReview:
        """
        Review an anomaly detection result using LLM.
        
        Args:
            product: Product
            current_price: Current price
            ml_result: ML anomaly detection result
            db: Database session
            
        Returns:
            LLMReview with validation and adjustments
        """
        if not settings.ai_llm_review_enabled:
            # Return neutral review if disabled
            return LLMReview(
                is_valid=True,
                confidence_adjustment=0.0,
                explanation="LLM review disabled",
                suggested_features=[],
            )
        
        # Only review high-confidence anomalies to save costs
        if ml_result.anomaly_score < settings.ai_llm_review_threshold:
            return LLMReview(
                is_valid=True,
                confidence_adjustment=0.0,
                explanation="Below LLM review threshold",
                suggested_features=[],
            )
        
        try:
            # Get price history for context
            price_history = await self._get_price_history_context(db, product.id)
            
            # Build prompt
            prompt = self._build_review_prompt(
                product,
                current_price,
                ml_result,
                price_history,
            )
            
            system_prompt = """You are an expert at detecting pricing errors in e-commerce.
Review the anomaly detection results and provide:
1. Whether this is a valid price error (true anomaly)
2. Confidence adjustment (-0.2 to +0.2)
3. Human-readable explanation
4. Suggested features that might help
5. Any edge case notes

Respond in JSON format with keys: is_valid, confidence_adjustment, explanation, suggested_features, edge_case_notes."""
            
            response_schema = {
                "type": "object",
                "properties": {
                    "is_valid": {"type": "boolean"},
                    "confidence_adjustment": {"type": "number"},
                    "explanation": {"type": "string"},
                    "suggested_features": {"type": "array", "items": {"type": "string"}},
                    "edge_case_notes": {"type": "string"},
                },
                "required": ["is_valid", "confidence_adjustment", "explanation", "suggested_features"],
            }
            
            result = await llm_service.call_llm_structured(
                prompt=prompt,
                response_schema=response_schema,
                system_prompt=system_prompt,
            )
            
            return LLMReview(
                is_valid=result.get("is_valid", True),
                confidence_adjustment=float(result.get("confidence_adjustment", 0.0)),
                explanation=result.get("explanation", ""),
                suggested_features=result.get("suggested_features", []),
                edge_case_notes=result.get("edge_case_notes"),
            )
            
        except Exception as e:
            logger.error(f"LLM review failed: {e}")
            # Fail open - return neutral review
            return LLMReview(
                is_valid=True,
                confidence_adjustment=0.0,
                explanation=f"LLM review error: {e}",
                suggested_features=[],
            )
    
    def _build_review_prompt(
        self,
        product: Product,
        current_price: Decimal,
        ml_result: AnomalyResult,
        price_history: List[dict],
    ) -> str:
        """Build prompt for LLM review."""
        prompt_parts = [
            f"Product: {product.title or 'Unknown'}",
            f"Store: {product.store}",
            f"SKU: {product.sku}",
            f"Current Price: ${current_price:.2f}",
        ]
        
        if product.msrp:
            prompt_parts.append(f"MSRP: ${product.msrp:.2f}")
        
        if product.baseline_price:
            prompt_parts.append(f"Baseline Price: ${product.baseline_price:.2f}")
        
        prompt_parts.append("\nAnomaly Detection Results:")
        prompt_parts.append(f"- Anomaly Score: {ml_result.anomaly_score:.3f}")
        prompt_parts.append(f"- Confidence: {ml_result.confidence:.3f}")
        prompt_parts.append(f"- Detection Methods: {', '.join(ml_result.detection_methods)}")
        prompt_parts.append(f"- Reasons: {'; '.join(ml_result.reasons)}")
        
        if ml_result.z_score is not None:
            prompt_parts.append(f"- Z-Score: {ml_result.z_score:.2f}")
        
        if price_history:
            prompt_parts.append(f"\nRecent Price History (last {len(price_history)} prices):")
            for i, ph in enumerate(price_history[:10], 1):
                prompt_parts.append(f"  {i}. ${ph['price']:.2f} on {ph['date']}")
        
        prompt_parts.append("\nIs this a genuine pricing error or a false positive?")
        prompt_parts.append("Consider:")
        prompt_parts.append("- Is the price drop too large to be legitimate?")
        prompt_parts.append("- Are there seasonal patterns or sales events?")
        prompt_parts.append("- Could this be a data quality issue?")
        prompt_parts.append("- Is the product description consistent with the price?")
        
        return "\n".join(prompt_parts)
    
    async def _get_price_history_context(
        self,
        db: AsyncSession,
        product_id: int,
        limit: int = 20,
    ) -> List[dict]:
        """Get price history for context."""
        from sqlalchemy import select
        
        query = select(PriceHistory).where(
            PriceHistory.product_id == product_id
        ).order_by(PriceHistory.fetched_at.desc()).limit(limit)
        
        result = await db.execute(query)
        history = result.scalars().all()
        
        return [
            {
                "price": float(h.price),
                "date": h.fetched_at.strftime("%Y-%m-%d %H:%M"),
            }
            for h in reversed(history)  # Reverse to show chronological order
        ]
    
    async def explain_anomaly(
        self,
        product: Product,
        price_history: List[PriceHistory],
        current_price: Decimal,
    ) -> str:
        """
        Generate human-readable explanation of an anomaly.
        
        Args:
            product: Product
            price_history: Price history
            current_price: Current price
            
        Returns:
            Explanation text
        """
        if not settings.ai_llm_review_enabled:
            return "LLM explanation disabled"
        
        try:
            prompt = f"""Explain why this price might be an error:

Product: {product.title or 'Unknown'}
Current Price: ${current_price:.2f}
"""
            
            if price_history:
                prompt += "\nPrice History:\n"
                for h in price_history[-10:]:
                    prompt += f"  ${h.price:.2f} on {h.fetched_at.strftime('%Y-%m-%d')}\n"
            
            prompt += "\nProvide a brief explanation (2-3 sentences) of why this price appears anomalous."
            
            explanation = await llm_service.call_llm(
                prompt=prompt,
                system_prompt="You are an expert at explaining pricing anomalies. Be concise and clear.",
            )
            
            return explanation
        except Exception as e:
            logger.warning(f"Failed to generate explanation: {e}")
            return "Explanation unavailable"
    
    async def validate_anomaly(
        self,
        anomaly_candidate: dict,
    ) -> bool:
        """
        Validate if an anomaly candidate is a true price error.
        
        Args:
            anomaly_candidate: Dictionary with anomaly details
            
        Returns:
            True if valid anomaly, False otherwise
        """
        if not settings.ai_llm_review_enabled:
            return True  # Fail open
        
        try:
            prompt = f"""Is this a genuine pricing error?

{anomaly_candidate.get('description', 'Anomaly detected')}

Price: ${anomaly_candidate.get('price', 0):.2f}
Anomaly Score: {anomaly_candidate.get('score', 0):.3f}

Respond with only 'true' or 'false'."""
            
            response = await llm_service.call_llm(
                prompt=prompt,
                system_prompt="You are an expert at detecting pricing errors. Respond with only 'true' or 'false'.",
            )
            
            return response.strip().lower() == "true"
        except Exception as e:
            logger.warning(f"Anomaly validation failed: {e}")
            return True  # Fail open


# Global LLM reviewer instance
llm_anomaly_reviewer = LLMAnomalyReviewer()
