"""Text structuring service for normalizing product text."""

import logging
from dataclasses import dataclass
from typing import Optional

from src.ai.attribute_extractor import attribute_extractor
from src.ai.llm_service import llm_service
from src.ai.text_processor import text_processor
from src.config import settings
from src.db.models import Product

logger = logging.getLogger(__name__)


@dataclass
class StructuredProduct:
    """Structured product representation."""
    
    brand: Optional[str] = None
    model: Optional[str] = None
    spec: Optional[str] = None
    normalized_text: str = ""
    category: Optional[str] = None


class TextStructurer:
    """
    Normalize and structure product text.
    
    Features:
    - Parse into standard format: "Brand - Model - Spec"
    - Category classification
    - Template matching
    - LLM-based rewriting
    """
    
    def structure_product_text(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> StructuredProduct:
        """
        Structure product text into normalized format.
        
        Args:
            title: Product title
            description: Optional description
            
        Returns:
            StructuredProduct object
        """
        if not title:
            return StructuredProduct()
        
        # Extract attributes
        attributes = await attribute_extractor.extract_attributes(
            title=title,
            description=description,
            use_llm=settings.ai_attribute_extraction_enabled,
        )
        
        # Build normalized text
        normalized_text = self.normalize_to_template(attributes, title)
        
        # Note: classify_category is async, but we'll call it separately if needed
        category = attributes.get("category")
        
        return StructuredProduct(
            brand=attributes.get("brand"),
            model=attributes.get("model"),
            spec=self._extract_spec(title, attributes),
            normalized_text=normalized_text,
            category=category,
        )
    
    def normalize_to_template(
        self,
        attributes: dict,
        original_title: str,
    ) -> str:
        """
        Normalize product text to standard template: "Brand - Model - Spec".
        
        Args:
            attributes: Extracted attributes
            original_title: Original title
            
        Returns:
            Normalized text
        """
        parts = []
        
        if attributes.get("brand"):
            parts.append(attributes["brand"])
        
        if attributes.get("model"):
            parts.append(attributes["model"])
        
        # Add remaining spec if available
        if attributes.get("size"):
            parts.append(f"Size: {attributes['size']}")
        
        if attributes.get("color"):
            parts.append(f"Color: {attributes['color']}")
        
        if parts:
            normalized = " - ".join(parts)
        else:
            # Fallback: use cleaned original title
            normalized = text_processor.clean_product_title(original_title)
        
        return normalized
    
    async def classify_category(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Classify product category.
        
        Args:
            title: Product title
            description: Optional description
            
        Returns:
            Category name or None
        """
        text = title
        if description:
            text = f"{title} {description}"
        
        # First try attribute extractor
        attributes = await attribute_extractor.extract_attributes(title, description, use_llm=False)
        if attributes.get("category"):
            return attributes["category"]
        
        # Use LLM if enabled
        if settings.ai_attribute_extraction_enabled:
            try:
                return await self._classify_with_llm(text)
            except Exception as e:
                logger.warning(f"LLM category classification failed: {e}")
        
        return None
    
    async def _classify_with_llm(self, text: str) -> Optional[str]:
        """Classify category using LLM."""
        prompt = f"""Classify this product into one of these categories:
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
        
        try:
            response = await llm_service.call_llm(
                prompt=prompt,
                system_prompt="You are a product categorization expert. Respond with only the category name.",
            )
            category = response.strip().lower()
            
            # Validate category
            valid_categories = [
                "electronics", "apparel", "home", "sports", "toys", "books", "food", "other"
            ]
            if category in valid_categories:
                return category
        except Exception as e:
            logger.warning(f"LLM category classification failed: {e}")
        
        return None
    
    def _extract_spec(self, title: str, attributes: dict) -> Optional[str]:
        """Extract specification details from title."""
        # Remove brand and model from title to get remaining spec
        cleaned = title
        if attributes.get("brand"):
            cleaned = cleaned.replace(attributes["brand"], "").strip()
        if attributes.get("model"):
            cleaned = cleaned.replace(attributes["model"], "").strip()
        
        # Clean up
        cleaned = text_processor.normalize_text(cleaned, lowercase=False)
        
        if cleaned and len(cleaned) > 5:
            return cleaned[:100]  # Limit length
        
        return None
    
    async def normalize_with_llm(
        self,
        product: Product,
    ) -> str:
        """
        Use LLM to rewrite product text into normalized format.
        
        Args:
            product: Product object
            
        Returns:
            Normalized text
        """
        if not settings.ai_attribute_extraction_enabled:
            return product.title or ""
        
        prompt = f"""Normalize this product title into a standard format:
"Brand - Model - Specifications"

Original: {product.title or 'Unknown'}

Return only the normalized text, no explanation."""
        
        try:
            normalized = await llm_service.call_llm(
                prompt=prompt,
                system_prompt="You are an expert at normalizing product titles. Return only the normalized text.",
            )
            return normalized.strip()
        except Exception as e:
            logger.warning(f"LLM normalization failed: {e}")
            return product.title or ""


# Global text structurer instance
text_structurer = TextStructurer()
