"""Attribute extraction from product text using NER, rules, and LLM."""

import logging
import re
from typing import Any, Dict, List, Optional

from src.ai.llm_service import llm_service
from src.ai.text_processor import text_processor
from src.config import settings

logger = logging.getLogger(__name__)


class AttributeExtractor:
    """
    Extract structured attributes from product text.
    
    Uses multiple methods:
    - NER (Named Entity Recognition) via spaCy
    - Rule-based extraction (regex, dictionaries)
    - LLM-based extraction for complex cases
    """
    
    # Common brand patterns
    BRAND_PATTERNS = [
        r'\b([A-Z][a-z]+)\s+(?:[A-Z][a-z]+\s+)?(?:Pro|Max|Plus|Ultra|Elite|Premium)\b',
        r'\b([A-Z][a-z]+)\s+(?:[A-Z][a-z]+)\b',  # Two-word brands
    ]
    
    # Size patterns
    SIZE_PATTERNS = [
        r'\b(\d+(?:\.\d+)?)\s*(?:inch|in|"|cm|mm|oz|lb|kg|g)\b',
        r'\b(\d+)\s*x\s*(\d+)\s*(?:inch|in|cm|mm)\b',  # Dimensions
    ]
    
    # Color patterns
    COLOR_PATTERNS = [
        r'\b(black|white|red|blue|green|yellow|orange|purple|pink|brown|gray|grey|silver|gold|bronze)\b',
    ]
    
    async def extract_attributes(
        self,
        title: str,
        description: Optional[str] = None,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """
        Extract attributes from product text.
        
        Args:
            title: Product title
            description: Optional product description
            use_llm: Whether to use LLM for complex cases
            
        Returns:
            Dictionary of extracted attributes
        """
        if not title:
            return {}
        
        attributes = {}
        
        # 1. NER extraction
        if settings.enable_ner:
            ner_attributes = self.extract_with_ner(title)
            attributes.update(ner_attributes)
        
        # 2. Rule-based extraction
        rule_attributes = self.extract_with_rules(title, description)
        attributes.update(rule_attributes)
        
        # 3. LLM extraction for complex cases (if enabled and needed)
        if use_llm and settings.ai_attribute_extraction_enabled:
            # Only use LLM if we didn't extract much with other methods
            if len(attributes) < 3 or not attributes.get("brand"):
                try:
                    llm_attributes = await self.extract_with_llm(title, description)
                    # Merge LLM results (LLM takes precedence)
                    for key, value in llm_attributes.items():
                        if value:  # Only override if LLM found something
                            attributes[key] = value
                except Exception as e:
                    logger.warning(f"LLM attribute extraction failed: {e}")
        
        return attributes
    
    def extract_with_ner(self, text: str) -> Dict[str, List[str]]:
        """
        Extract attributes using Named Entity Recognition.
        
        Args:
            text: Input text
            
        Returns:
            Dictionary mapping entity types to lists of entities
        """
        entities = text_processor.extract_entities(text)
        
        # Map spaCy entity types to our attribute types
        attribute_map = {
            "PERSON": "brand",  # Sometimes brands are tagged as PERSON
            "ORG": "brand",  # Organizations are often brands
            "PRODUCT": "model",  # Products might be models
        }
        
        result = {}
        for entity_type, entity_list in entities.items():
            mapped_type = attribute_map.get(entity_type)
            if mapped_type:
                if mapped_type not in result:
                    result[mapped_type] = []
                result[mapped_type].extend(entity_list)
        
        return result
    
    def extract_with_rules(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract attributes using rule-based patterns.
        
        Args:
            title: Product title
            description: Optional description
            
        Returns:
            Dictionary of extracted attributes
        """
        text = title
        if description:
            text = f"{title} {description}"
        
        attributes = {}
        
        # Extract brand (first capitalized word or known brand pattern)
        brand = self._extract_brand(text)
        if brand:
            attributes["brand"] = brand
        
        # Extract model (often after brand, or in specific patterns)
        model = self._extract_model(text, brand)
        if model:
            attributes["model"] = model
        
        # Extract size
        size = self._extract_size(text)
        if size:
            attributes["size"] = size
        
        # Extract color
        color = self._extract_color(text)
        if color:
            attributes["color"] = color
        
        # Extract category (simple keyword-based)
        category = self._extract_category(text)
        if category:
            attributes["category"] = category
        
        return attributes
    
    def _extract_brand(self, text: str) -> Optional[str]:
        """Extract brand from text."""
        # Try known brand patterns first
        for pattern in self.BRAND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Fallback: first capitalized word (common brand pattern)
        words = text.split()
        for word in words[:3]:  # Check first 3 words
            if word and word[0].isupper() and len(word) > 2:
                # Skip common words
                if word.lower() not in ["the", "new", "best", "top", "premium"]:
                    return word
        
        return None
    
    def _extract_model(self, text: str, brand: Optional[str] = None) -> Optional[str]:
        """Extract model number/name from text."""
        # Common model patterns
        model_patterns = [
            r'\b([A-Z0-9]{3,}-?[A-Z0-9]{2,})\b',  # Alphanumeric codes
            r'\b(Model\s+[A-Z0-9-]+)\b',  # "Model XYZ"
            r'\b([A-Z][a-z]+\s+\d+[A-Z]?)\b',  # "iPhone 14" style
        ]
        
        for pattern in model_patterns:
            matches = re.findall(pattern, text)
            if matches:
                model = matches[0]
                # Exclude brand if found
                if brand and brand.lower() in model.lower():
                    continue
                return model.strip()
        
        return None
    
    def _extract_size(self, text: str) -> Optional[str]:
        """Extract size from text."""
        for pattern in self.SIZE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) > 1:
                    return f"{match.group(1)}x{match.group(2)}"
                return match.group(1)
        
        return None
    
    def _extract_color(self, text: str) -> Optional[str]:
        """Extract color from text."""
        text_lower = text.lower()
        for pattern in self.COLOR_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                return match.group(1).capitalize()
        
        return None
    
    def _extract_category(self, text: str) -> Optional[str]:
        """Extract category from text using keywords."""
        text_lower = text.lower()
        
        category_keywords = {
            "electronics": ["tv", "television", "monitor", "laptop", "computer", "phone", "tablet", "headphones"],
            "apparel": ["shirt", "pants", "shoes", "jacket", "dress", "sweater"],
            "home": ["furniture", "chair", "table", "sofa", "bed", "lamp"],
            "sports": ["bike", "bicycle", "treadmill", "weights", "gym"],
            "toys": ["toy", "game", "puzzle", "doll"],
        }
        
        for category, keywords in category_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return category
        
        return None
    
    async def extract_with_llm(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract attributes using LLM.
        
        Args:
            title: Product title
            description: Optional description
            
        Returns:
            Dictionary of extracted attributes
        """
        text = title
        if description:
            text = f"{title}\n\n{description}"
        
        prompt = f"""Extract structured attributes from this product text:

{text}

Extract:
- brand: Brand name
- model: Model number or name
- size: Size/dimensions if mentioned
- color: Color if mentioned
- category: Product category

Respond with JSON only."""
        
        response_schema = {
            "type": "object",
            "properties": {
                "brand": {"type": "string"},
                "model": {"type": "string"},
                "size": {"type": "string"},
                "color": {"type": "string"},
                "category": {"type": "string"},
            },
        }
        
        try:
            result = await llm_service.call_llm_structured(
                prompt=prompt,
                response_schema=response_schema,
                system_prompt="You are an expert at extracting product attributes from text. Return only valid JSON.",
            )
            
            # Filter out None/empty values
            return {k: v for k, v in result.items() if v}
        except Exception as e:
            logger.warning(f"LLM attribute extraction failed: {e}")
            return {}


# Global attribute extractor instance
attribute_extractor = AttributeExtractor()
