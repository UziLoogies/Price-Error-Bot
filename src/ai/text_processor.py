"""Text processing pipeline for product text normalization and NLP."""

import html
import logging
import re
from typing import Any, Dict, List, Optional

import logging
logger = logging.getLogger(__name__)

try:
    import spacy
    from spacy.lang.en import English
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logger.warning("spaCy not available. NER features will be disabled.")

from src.config import settings


class TextProcessor:
    """
    Text processing pipeline for product text.
    
    Features:
    - Text normalization (lowercase, remove HTML, expand abbreviations)
    - Language detection
    - Tokenization
    - Stopword removal
    - spaCy integration for NER
    """
    
    def __init__(self):
        self._nlp: Optional[Any] = None
        self._spacy_loaded = False
        
        # Common abbreviations in product titles
        self._abbreviations = {
            "w/": "with",
            "w/o": "without",
            "&": "and",
            "+": "plus",
            "vs": "versus",
            "vs.": "versus",
            "approx": "approximately",
            "approx.": "approximately",
            "est": "estimated",
            "est.": "estimated",
            "inc": "including",
            "inc.": "including",
            "excl": "excluding",
            "excl.": "excluding",
        }
    
    def _load_spacy(self):
        """Load spaCy model if available."""
        if not SPACY_AVAILABLE or not settings.enable_ner:
            return
        
        if self._spacy_loaded:
            return
        
        try:
            logger.info(f"Loading spaCy model: {settings.spacy_model}")
            self._nlp = spacy.load(settings.spacy_model)
            self._spacy_loaded = True
            logger.info("spaCy model loaded successfully")
        except OSError:
            logger.warning(
                f"spaCy model '{settings.spacy_model}' not found. "
                "Install with: python -m spacy download en_core_web_sm"
            )
        except Exception as e:
            logger.warning(f"Failed to load spaCy model: {e}")
    
    def normalize_text(self, text: str, lowercase: bool = True, remove_html: bool = True) -> str:
        """
        Normalize text for processing.
        
        Args:
            text: Input text
            lowercase: Convert to lowercase
            remove_html: Remove HTML entities and tags
            
        Returns:
            Normalized text
        """
        if not text:
            return ""
        
        # Remove HTML entities
        if remove_html:
            text = html.unescape(text)
            # Remove HTML tags (simple regex)
            text = re.sub(r'<[^>]+>', '', text)
        
        # Expand abbreviations
        for abbrev, expansion in self._abbreviations.items():
            text = re.sub(rf'\b{re.escape(abbrev)}\b', expansion, text, flags=re.IGNORECASE)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Convert to lowercase if requested
        if lowercase:
            text = text.lower()
        
        return text
    
    def detect_language(self, text: str) -> str:
        """
        Detect language of text (simple heuristic).
        
        Args:
            text: Input text
            
        Returns:
            Language code (e.g., 'en', 'es')
        """
        # Simple heuristic: check for common English words
        # For production, use a proper language detection library
        if not text:
            return "unknown"
        
        text_lower = text.lower()
        english_indicators = [
            "the", "and", "or", "for", "with", "from", "this", "that",
            "product", "price", "sale", "deal", "discount"
        ]
        
        english_count = sum(1 for word in english_indicators if word in text_lower)
        if english_count >= 2:
            return "en"
        
        # Default to English for product listings (most common)
        return "en"
    
    def extract_tokens(self, text: str, remove_stopwords: bool = True) -> List[str]:
        """
        Extract tokens from text.
        
        Args:
            text: Input text
            remove_stopwords: Remove common stopwords
            
        Returns:
            List of tokens
        """
        if not text:
            return []
        
        # Simple tokenization (split on whitespace and punctuation)
        tokens = re.findall(r'\b\w+\b', text.lower())
        
        if remove_stopwords:
            # Common English stopwords
            stopwords = {
                "a", "an", "and", "are", "as", "at", "be", "by", "for",
                "from", "has", "he", "in", "is", "it", "its", "of", "on",
                "that", "the", "to", "was", "will", "with", "this"
            }
            tokens = [t for t in tokens if t not in stopwords and len(t) > 1]
        
        return tokens
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract named entities using spaCy NER.
        
        Args:
            text: Input text
            
        Returns:
            Dictionary mapping entity types to lists of entities
        """
        if not SPACY_AVAILABLE or not settings.enable_ner:
            return {}
        
        self._load_spacy()
        
        if not self._nlp:
            return {}
        
        try:
            doc = self._nlp(text)
            entities = {}
            
            for ent in doc.ents:
                entity_type = ent.label_
                entity_text = ent.text.strip()
                
                if entity_type not in entities:
                    entities[entity_type] = []
                
                if entity_text not in entities[entity_type]:
                    entities[entity_type].append(entity_text)
            
            return entities
        except Exception as e:
            logger.warning(f"NER extraction failed: {e}")
            return {}
    
    def clean_product_title(self, title: str) -> str:
        """
        Clean and normalize a product title.
        
        Args:
            title: Product title
            
        Returns:
            Cleaned title
        """
        if not title:
            return ""
        
        # Normalize
        cleaned = self.normalize_text(title, lowercase=False, remove_html=True)
        
        # Remove common prefixes/suffixes that add noise
        prefixes_to_remove = [
            r'^\[.*?\]\s*',  # [BEST SELLER], etc.
            r'^\(.*?\)\s*',  # (NEW), etc.
        ]
        
        for pattern in prefixes_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    def extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """
        Extract important keywords from text.
        
        Args:
            text: Input text
            max_keywords: Maximum number of keywords to return
            
        Returns:
            List of keywords (sorted by importance)
        """
        tokens = self.extract_tokens(text, remove_stopwords=True)
        
        # Simple frequency-based keyword extraction
        from collections import Counter
        word_freq = Counter(tokens)
        
        # Filter out very short words and get most common
        keywords = [
            word for word, count in word_freq.most_common(max_keywords * 2)
            if len(word) >= 3
        ]
        
        return keywords[:max_keywords]


# Global text processor instance
text_processor = TextProcessor()
