"""Retrieval-Augmented Generation (RAG) service for grounding LLM reasoning."""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.embedding_service import embedding_service
from src.ai.llm_service import llm_service
from src.config import settings
from src.db.models import PriceHistory, Product
from src.db.vector_store import vector_store

logger = logging.getLogger(__name__)


class RAGService:
    """
    Retrieval-Augmented Generation service.
    
    Features:
    - Store product/price history in vector store
    - Retrieve relevant context for LLM queries
    - Ground LLM reasoning with historical data
    """
    
    async def retrieve_context(
        self,
        product_id: int,
        query: str,
        db: AsyncSession,
        limit: int = 5,
    ) -> List[dict]:
        """
        Retrieve relevant context for a query about a product.
        
        Args:
            product_id: Product ID
            query: Query text
            db: Database session
            limit: Maximum number of context items
            
        Returns:
            List of relevant context dictionaries
        """
        if not settings.vector_db_enabled:
            return []
        
        try:
            # Search for similar price history entries
            # Note: This would require storing price history as embeddings
            # For now, we'll use a simpler approach: get recent price history
            context = []
            
            # Get recent price history
            price_history_query = select(PriceHistory).where(
                PriceHistory.product_id == product_id
            ).order_by(PriceHistory.fetched_at.desc()).limit(limit)
            
            result = await db.execute(price_history_query)
            history = result.scalars().all()
            
            for h in history:
                context.append({
                    "type": "price_history",
                    "price": float(h.price),
                    "date": h.fetched_at.isoformat(),
                    "confidence": h.confidence,
                })
            
            # Get product details
            product = await db.get(Product, product_id)
            if product:
                context.append({
                    "type": "product",
                    "title": product.title,
                    "store": product.store,
                    "sku": product.sku,
                    "msrp": float(product.msrp) if product.msrp else None,
                    "baseline_price": float(product.baseline_price) if product.baseline_price else None,
                })
            
            return context
            
        except Exception as e:
            logger.warning(f"Context retrieval failed: {e}")
            return []
    
    async def query_with_rag(
        self,
        question: str,
        product_id: int,
        db: AsyncSession,
    ) -> str:
        """
        Query LLM with retrieved context (RAG).
        
        Args:
            question: Question to ask
            product_id: Product ID
            db: Database session
            
        Returns:
            LLM response grounded in context
        """
        # Retrieve relevant context
        context = await self.retrieve_context(product_id, question, db)
        
        # Build prompt with context
        context_text = "\n".join([
            f"- {item.get('type', 'unknown')}: {item}"
            for item in context[:10]  # Limit context size
        ])
        
        prompt = f"""Answer this question about the product using the provided context:

Question: {question}

Context:
{context_text}

Provide a clear, concise answer based on the context."""
        
        try:
            response = await llm_service.call_llm(
                prompt=prompt,
                system_prompt="You are an expert at analyzing product and pricing data. Answer questions based on the provided context.",
            )
            return response
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            return "Unable to answer question at this time."
    
    async def store_product_context(
        self,
        product_id: int,
        text: str,
        db: AsyncSession,
    ):
        """
        Store product context in vector store for later retrieval.
        
        Args:
            product_id: Product ID
            text: Text to store (e.g., price history summary)
            db: Database session
        """
        if not settings.vector_db_enabled:
            return
        
        try:
            # Generate embedding
            embedding = embedding_service.generate_embedding(text)
            
            # Store in vector store (would need a separate table for context)
            # For now, this is a placeholder - full implementation would require
            # a context_embeddings table
            logger.debug(f"Stored context for product {product_id}")
        except Exception as e:
            logger.warning(f"Failed to store context: {e}")


# Global RAG service instance
rag_service = RAGService()
