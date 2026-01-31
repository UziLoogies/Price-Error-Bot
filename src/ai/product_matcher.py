"""Product matching service using semantic embeddings."""

import hashlib
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.embedding_service import embedding_service
from src.ai.text_processor import text_processor
from src.config import settings
from src.db.models import Product, ProductEmbedding, ProductMatch
from src.db.vector_store import vector_store

logger = logging.getLogger(__name__)


@dataclass
class ProductMatchResult:
    """Result of product matching."""
    
    product_id: int
    store: str
    sku: str
    title: str
    similarity_score: float
    match_method: str
    confidence: float


class ProductMatcher:
    """
    Semantic product matching service.
    
    Features:
    - Generate embeddings for product titles/descriptions
    - Store embeddings in database
    - Find similar products using cosine similarity
    - Cross-store matching logic
    - Confidence scoring
    """
    
    def __init__(self):
        self._embedding_dim = None
    
    def _get_text_for_embedding(self, product: Product) -> str:
        """
        Get text to embed for a product.
        
        Combines title and other available text.
        """
        text_parts = []
        
        if product.title:
            # Clean and normalize title
            cleaned_title = text_processor.clean_product_title(product.title)
            text_parts.append(cleaned_title)
        
        # Could add description, brand, etc. in the future
        return " ".join(text_parts)
    
    def _get_text_hash(self, text: str) -> str:
        """Generate hash of text for caching."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    async def generate_product_embedding(
        self,
        product: Product,
        model_name: Optional[str] = None,
    ) -> np.ndarray:
        """
        Generate embedding for a product.
        
        Args:
            product: Product to embed
            model_name: Optional model name (defaults to configured model)
            
        Returns:
            Embedding vector
        """
        text = self._get_text_for_embedding(product)
        
        if not text or not text.strip():
            logger.warning(f"Empty text for product {product.id}, using zero vector")
            return np.zeros(768)  # Default dimension
        
        embedding = embedding_service.generate_embedding(text)
        return embedding
    
    async def store_embedding(
        self,
        db: AsyncSession,
        product: Product,
        embedding: Optional[np.ndarray] = None,
        model_name: Optional[str] = None,
    ):
        """
        Store embedding for a product in database.
        
        Args:
            db: Database session
            product: Product
            embedding: Optional pre-computed embedding
            model_name: Optional model name
        """
        if not settings.vector_db_enabled or not settings.ai_product_matching_enabled:
            return
        
        model_name = model_name or (settings.retail_embedding_model if settings.use_retail_embedding else settings.embedding_model)
        
        if embedding is None:
            embedding = await self.generate_product_embedding(product, model_name)
        
        text = self._get_text_for_embedding(product)
        text_hash = self._get_text_hash(text)
        
        await vector_store.upsert_embedding(
            db=db,
            table="product_embeddings",
            product_id=product.id,
            embedding=embedding,
            model_name=model_name,
            text_hash=text_hash,
        )
    
    async def find_similar_products(
        self,
        db: AsyncSession,
        product: Product,
        threshold: Optional[float] = None,
        limit: int = 10,
        exclude_same_store: bool = True,
    ) -> List[ProductMatchResult]:
        """
        Find similar products using semantic matching.
        
        Args:
            db: Database session
            product: Product to find matches for
            threshold: Similarity threshold (defaults to settings.similarity_threshold)
            limit: Maximum number of results
            exclude_same_store: Exclude products from same store
            
        Returns:
            List of ProductMatch objects
        """
        if not settings.vector_db_enabled or not settings.ai_product_matching_enabled:
            return []
        
        threshold = threshold or settings.similarity_threshold
        
        # Get or generate embedding
        model_name = settings.retail_embedding_model if settings.use_retail_embedding else settings.embedding_model
        
        # Check if embedding exists in DB
        embedding = await vector_store.get_embedding(
            db=db,
            table="product_embeddings",
            product_id=product.id,
            model_name=model_name,
        )
        
        if embedding is None:
            # Generate and store embedding
            embedding = await self.generate_product_embedding(product, model_name)
            await self.store_embedding(db, product, embedding, model_name)
        
        # Search for similar products
        exclude_ids = [product.id]
        if exclude_same_store:
            # Get IDs of products from same store to exclude
            same_store_query = select(Product.id).where(Product.store == product.store)
            same_store_result = await db.execute(same_store_query)
            same_store_ids = [row[0] for row in same_store_result.fetchall()]
            exclude_ids.extend(same_store_ids)
        
        similar_results = await vector_store.search_similar(
            db=db,
            table="product_embeddings",
            column="embedding",
            embedding=embedding,
            limit=limit * 2,  # Get more to filter
            threshold=threshold,
            exclude_ids=exclude_ids,
        )
        
        # Load full product details
        matches = []
        for result in similar_results[:limit]:
            product_id = result["id"]
            
            # Get product details
            product_query = select(Product).where(Product.id == product_id)
            product_result = await db.execute(product_query)
            matched_product = product_result.scalar_one_or_none()
            
            if not matched_product:
                continue
            
            similarity = float(result["similarity"])
            
            # Calculate confidence based on similarity and other factors
            confidence = self._calculate_match_confidence(
                product,
                matched_product,
                similarity,
            )
            
            matches.append(ProductMatchResult(
                product_id=matched_product.id,
                store=matched_product.store,
                sku=matched_product.sku,
                title=matched_product.title or "",
                similarity_score=similarity,
                match_method="embedding",
                confidence=confidence,
            ))
        
        return matches
    
    def _calculate_match_confidence(
        self,
        product1: Product,
        product2: Product,
        similarity: float,
    ) -> float:
        """
        Calculate confidence score for a product match.
        
        Args:
            product1: First product
            product2: Second product
            similarity: Cosine similarity score
            
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = similarity  # Start with similarity as base
        
        # Boost if prices are similar (within 10%)
        if product1.baseline_price and product2.baseline_price:
            price_diff = abs(float(product1.baseline_price - product2.baseline_price))
            avg_price = (float(product1.baseline_price) + float(product2.baseline_price)) / 2
            if avg_price > 0:
                price_ratio = price_diff / avg_price
                if price_ratio < 0.1:  # Within 10%
                    confidence += 0.1
                elif price_ratio < 0.2:  # Within 20%
                    confidence += 0.05
        
        # Boost if MSRPs match
        if product1.msrp and product2.msrp:
            if abs(float(product1.msrp - product2.msrp)) < 0.01:  # Same MSRP
                confidence += 0.1
        
        # Clamp to valid range
        return min(1.0, max(0.0, confidence))
    
    async def match_products_cross_store(
        self,
        db: AsyncSession,
        store1: str,
        sku1: str,
        store2: str,
        sku2: str,
    ) -> bool:
        """
        Check if two products from different stores are matches.
        
        Args:
            db: Database session
            store1: First store
            sku1: First SKU
            store2: Second store
            sku2: Second SKU
            
        Returns:
            True if products match, False otherwise
        """
        # Get products
        query1 = select(Product).where(Product.store == store1, Product.sku == sku1)
        query2 = select(Product).where(Product.store == store2, Product.sku == sku2)
        
        result1 = await db.execute(query1)
        result2 = await db.execute(query2)
        
        product1 = result1.scalar_one_or_none()
        product2 = result2.scalar_one_or_none()
        
        if not product1 or not product2:
            return False
        
        # Find similar products
        matches = await self.find_similar_products(
            db=db,
            product=product1,
            threshold=settings.similarity_threshold,
            limit=5,
            exclude_same_store=True,
        )
        
        # Check if product2 is in matches
        for match in matches:
            if match.product_id == product2.id:
                return True
        
        return False
    
    async def batch_update_embeddings(
        self,
        db: AsyncSession,
        products: List[Product],
        model_name: Optional[str] = None,
    ):
        """
        Batch update embeddings for multiple products.
        
        Args:
            db: Database session
            products: List of products
            model_name: Optional model name
        """
        if not settings.vector_db_enabled or not settings.ai_product_matching_enabled:
            return
        
        model_name = model_name or (settings.retail_embedding_model if settings.use_retail_embedding else settings.embedding_model)
        
        # Generate embeddings in batch
        texts = [self._get_text_for_embedding(p) for p in products]
        embeddings = embedding_service.generate_embeddings_batch(texts)
        
        # Prepare data for batch upsert
        embedding_data = []
        for product, embedding, text in zip(products, embeddings, texts, strict=True):
            if text and text.strip():  # Only include non-empty texts
                text_hash = self._get_text_hash(text)
                embedding_data.append({
                    "product_id": product.id,
                    "embedding": embedding,
                    "model_name": model_name,
                    "text_hash": text_hash,
                })
        
        if embedding_data:
            await vector_store.batch_upsert_embeddings(
                db=db,
                table="product_embeddings",
                embeddings=embedding_data,
            )
            logger.info(f"Batch updated {len(embedding_data)} product embeddings")


# Global product matcher instance
product_matcher = ProductMatcher()
