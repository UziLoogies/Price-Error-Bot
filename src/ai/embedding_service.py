"""Embedding generation service for product text."""

import hashlib
import logging
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating text embeddings using sentence transformers.
    
    Supports multiple models:
    - Generic models (all-mpnet-base-v2)
    - Retail-specific models (Ionio's retail-embedding-classifier-v1)
    
    Features:
    - Batch embedding generation
    - Model caching
    - Fallback to generic model if retail model unavailable
    """
    
    def __init__(self):
        self._generic_model: Optional[SentenceTransformer] = None
        self._retail_model: Optional[SentenceTransformer] = None
        self._model_loaded = False
        self._cache: dict[str, np.ndarray] = {}  # Simple in-memory cache
    
    def _load_model(self, model_name: str, is_retail: bool = False) -> Optional[SentenceTransformer]:
        """
        Load a sentence transformer model.
        
        Args:
            model_name: Hugging Face model name
            is_retail: Whether this is the retail-specific model
            
        Returns:
            Loaded model or None if loading fails
        """
        try:
            logger.info(f"Loading embedding model: {model_name}")
            model = SentenceTransformer(model_name)
            logger.info(f"Successfully loaded model: {model_name}")
            return model
        except Exception as e:
            logger.warning(f"Failed to load model {model_name}: {e}")
            if is_retail:
                logger.info("Will fallback to generic model")
            return None
    
    def _ensure_models_loaded(self):
        """Ensure at least one model is loaded."""
        if self._model_loaded:
            return
        
        # Try to load retail model first if enabled
        if settings.use_retail_embedding and settings.retail_embedding_model:
            self._retail_model = self._load_model(settings.retail_embedding_model, is_retail=True)
        
        # Load generic model (always needed as fallback or primary)
        if not self._generic_model:
            self._generic_model = self._load_model(settings.embedding_model, is_retail=False)
        
        if not self._generic_model and not self._retail_model:
            raise RuntimeError("Failed to load any embedding model")
        
        self._model_loaded = True
    
    def _get_model(self) -> SentenceTransformer:
        """
        Get the appropriate model to use.
        
        Returns:
            Retail model if available, otherwise generic model
        """
        self._ensure_models_loaded()
        
        if self._retail_model:
            return self._retail_model
        elif self._generic_model:
            return self._generic_model
        else:
            raise RuntimeError("No embedding model available")
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        model_name = settings.retail_embedding_model if self._retail_model else settings.embedding_model
        return f"{model_name}:{text_hash}"
    
    def generate_embedding(self, text: str, use_cache: bool = True) -> np.ndarray:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            use_cache: Whether to use cache
            
        Returns:
            768-D embedding vector
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        # Get model first to ensure correct cache key
        model = self._get_model()
        
        # Check cache
        if use_cache and settings.embedding_cache_enabled:
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                logger.debug(f"Cache hit for embedding: {cache_key[:16]}...")
                return self._cache[cache_key]
        
        # Generate embedding
        embedding = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        
        # Store in cache
        if use_cache and settings.embedding_cache_enabled:
            cache_key = self._get_cache_key(text)
            self._cache[cache_key] = embedding
        
        return embedding
    
    def generate_embeddings_batch(
        self,
        texts: List[str],
        use_cache: bool = True,
        batch_size: Optional[int] = None,
    ) -> List[np.ndarray]:
        """
        Generate embeddings for a batch of texts.
        
        Args:
            texts: List of texts to embed
            use_cache: Whether to use cache
            batch_size: Batch size (defaults to settings.embedding_batch_size)
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        batch_size = batch_size or settings.embedding_batch_size
        model = self._get_model()
        
        # Get embedding dimension from model
        embedding_dim = self.get_embedding_dimension()
        
        # Filter out empty texts
        valid_texts = [(i, text) for i, text in enumerate(texts) if text and text.strip()]
        if not valid_texts:
            return [np.zeros(embedding_dim) for _ in texts]  # Return zero vectors for empty texts
        
        # Check cache for each text
        cached_embeddings = {}
        texts_to_embed = []
        indices_to_embed = []
        
        for idx, text in valid_texts:
            if use_cache and settings.embedding_cache_enabled:
                cache_key = self._get_cache_key(text)
                if cache_key in self._cache:
                    cached_embeddings[idx] = self._cache[cache_key]
                    continue
            
            texts_to_embed.append(text)
            indices_to_embed.append(idx)
        
        # Generate embeddings for uncached texts
        if texts_to_embed:
            logger.debug(f"Generating embeddings for {len(texts_to_embed)} texts (batch size: {batch_size})")
            new_embeddings = model.encode(
                texts_to_embed,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=batch_size,
            )
            
            # Store in cache and map to indices
            for i, embedding in enumerate(new_embeddings):
                idx = indices_to_embed[i]
                text = texts_to_embed[i]
                cached_embeddings[idx] = embedding
                
                if use_cache and settings.embedding_cache_enabled:
                    cache_key = self._get_cache_key(text)
                    self._cache[cache_key] = embedding
        
        # Reconstruct full list with original order
        embedding_dim = self.get_embedding_dimension()
        result = []
        for i in range(len(texts)):
            if i in cached_embeddings:
                result.append(cached_embeddings[i])
            else:
                # Empty text - return zero vector
                result.append(np.zeros(embedding_dim))
        
        return result
    
    def get_embedding_dimension(self) -> int:
        """
        Get the dimension of embeddings produced by the current model.
        
        Returns:
            Embedding dimension (typically 768)
        """
        self._ensure_models_loaded()
        model = self._get_model()
        # Most sentence transformer models produce 768-D embeddings
        # Test with a dummy text to get actual dimension
        test_embedding = model.encode("test", normalize_embeddings=True)
        return len(test_embedding)
    
    def clear_cache(self):
        """Clear the embedding cache."""
        self._cache.clear()
        logger.info("Embedding cache cleared")
    
    def get_cache_size(self) -> int:
        """Get the number of cached embeddings."""
        return len(self._cache)


# Global embedding service instance
embedding_service = EmbeddingService()
