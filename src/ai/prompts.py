"""Centralized prompt templates for LLM interactions."""

from typing import Any, Dict, Optional

from pydantic import BaseModel


class AnomalyReviewPrompt(BaseModel):
    """Prompt schema for anomaly review."""
    
    product_title: str
    store: str
    sku: str
    current_price: float
    msrp: Optional[float] = None
    baseline_price: Optional[float] = None
    anomaly_score: float
    detection_methods: list[str]
    reasons: list[str]
    price_history: list[dict] = []
    
    def to_prompt(self) -> str:
        """Convert to prompt text."""
        parts = [
            f"Product: {self.product_title}",
            f"Store: {self.store}",
            f"SKU: {self.sku}",
            f"Current Price: ${self.current_price:.2f}",
        ]
        
        if self.msrp:
            parts.append(f"MSRP: ${self.msrp:.2f}")
        if self.baseline_price:
            parts.append(f"Baseline Price: ${self.baseline_price:.2f}")
        
        parts.append("\nAnomaly Detection Results:")
        parts.append(f"- Anomaly Score: {self.anomaly_score:.3f}")
        parts.append(f"- Detection Methods: {', '.join(self.detection_methods)}")
        parts.append(f"- Reasons: {'; '.join(self.reasons)}")
        
        if self.price_history:
            parts.append(f"\nRecent Price History:")
            for i, ph in enumerate(self.price_history[:10], 1):
                parts.append(f"  {i}. ${ph.get('price', 0):.2f} on {ph.get('date', 'unknown')}")
        
        parts.append("\nIs this a genuine pricing error or a false positive?")
        
        return "\n".join(parts)


class AttributeExtractionPrompt(BaseModel):
    """Prompt schema for attribute extraction."""
    
    title: str
    description: Optional[str] = None
    
    def to_prompt(self) -> str:
        """Convert to prompt text."""
        text = self.title
        if self.description:
            text = f"{self.title}\n\n{self.description}"
        
        return f"""Extract structured attributes from this product text:

{text}

Extract:
- brand: Brand name
- model: Model number or name
- size: Size/dimensions if mentioned
- color: Color if mentioned
- category: Product category

Respond with JSON only."""


class CategoryClassificationPrompt(BaseModel):
    """Prompt schema for category classification."""
    
    title: str
    description: Optional[str] = None
    
    def to_prompt(self) -> str:
        """Convert to prompt text."""
        text = self.title
        if self.description:
            text = f"{self.title} {self.description}"
        
        return f"""Classify this product into one of these categories:
- electronics
- apparel
- home
- sports
- toys
- books
- food
- other

Product: {text}

Respond with only the category name."""


class ProductMatchingPrompt(BaseModel):
    """Prompt schema for product matching validation."""
    
    product1_title: str
    product1_store: str
    product1_price: float
    product2_title: str
    product2_store: str
    product2_price: float
    similarity_score: float
    
    def to_prompt(self) -> str:
        """Convert to prompt text."""
        return f"""Are these two products the same?

Product 1: {self.product1_title} ({self.product1_store}) - ${self.product1_price:.2f}
Product 2: {self.product2_title} ({self.product2_store}) - ${self.product2_price:.2f}
Similarity Score: {self.similarity_score:.3f}

Respond with only 'true' or 'false'."""


# Response schemas for structured output
ANOMALY_REVIEW_SCHEMA = {
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

ATTRIBUTE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "size": {"type": "string"},
        "color": {"type": "string"},
        "category": {"type": "string"},
    },
}
