"""Vector database integration using pgvector."""

import logging
from typing import List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Vector database service for pgvector integration.
    
    Features:
    - Vector indexing (HNSW index)
    - Similarity search queries
    - Batch insert/update operations
    """
    
    def __init__(self):
        self._indexes_created = set()
    
    async def ensure_extension(self, db: AsyncSession):
        """Ensure pgvector extension is enabled."""
        try:
            await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await db.commit()
            logger.debug("pgvector extension enabled")
        except Exception as e:
            logger.warning(f"Failed to enable pgvector extension: {e}")
            # Extension might already exist, which is fine
    
    async def create_vector_index(
        self,
        db: AsyncSession,
        table: str,
        column: str,
        index_name: Optional[str] = None,
        index_type: str = "ivfflat",
    ):
        """
        Create vector index for similarity search.
        
        Args:
            db: Database session
            table: Table name
            column: Column name containing vectors
            index_name: Optional custom index name
            index_type: Index type ('ivfflat' or 'hnsw')
        """
        index_name = index_name or f"idx_{table}_{column}_vector"
        
        if index_name in self._indexes_created:
            return
        
        try:
            # Check if index already exists
            check_query = text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes 
                    WHERE indexname = :index_name
                )
            """)
            result = await db.execute(check_query, {"index_name": index_name})
            exists = result.scalar()
            
            if exists:
                logger.debug(f"Vector index {index_name} already exists")
                self._indexes_created.add(index_name)
                return
            
            # Create index based on type
            if index_type == "ivfflat":
                # IVFFlat index (faster creation, good for large datasets)
                # Lists parameter: number of clusters (default: rows / 1000, min 10)
                create_query = text(f"""
                    CREATE INDEX {index_name}
                    ON {table}
                    USING ivfflat ({column} vector_cosine_ops)
                    WITH (lists = 100)
                """)
            elif index_type == "hnsw":
                # HNSW index (better recall, slower creation)
                create_query = text(f"""
                    CREATE INDEX {index_name}
                    ON {table}
                    USING hnsw ({column} vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                """)
            else:
                raise ValueError(f"Unknown index type: {index_type}")
            
            await db.execute(create_query)
            await db.commit()
            self._indexes_created.add(index_name)
            logger.info(f"Created vector index {index_name} on {table}.{column}")
            
        except Exception as e:
            logger.error(f"Failed to create vector index {index_name}: {e}")
            await db.rollback()
            raise
    
    async def search_similar(
        self,
        db: AsyncSession,
        table: str,
        column: str,
        embedding: np.ndarray,
        limit: int = 10,
        threshold: Optional[float] = None,
        exclude_ids: Optional[List[int]] = None,
    ) -> List[dict]:
        """
        Search for similar vectors using cosine similarity.
        
        Args:
            db: Database session
            table: Table name
            column: Column name containing vectors
            embedding: Query embedding vector
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0.0-1.0)
            exclude_ids: List of IDs to exclude from results
            
        Returns:
            List of dictionaries with 'id', 'similarity', and other columns
        """
        threshold = threshold or settings.similarity_threshold
        
        # Convert numpy array to list for PostgreSQL
        embedding_list = embedding.tolist()
        embedding_str = "[" + ",".join(map(str, embedding_list)) + "]"
        
        # Build query with parameterized placeholders for exclude_ids
        exclude_clause = ""
        query_params = {
            "embedding": embedding_str,
            "threshold": threshold,
            "limit": limit,
        }
        
        if exclude_ids:
            # Validate all IDs are integers
            validated_ids = []
            for id_val in exclude_ids:
                if not isinstance(id_val, int):
                    try:
                        id_val = int(id_val)
                    except (ValueError, TypeError):
                        raise ValueError(f"Invalid exclude_id: {id_val} (must be integer)")
                validated_ids.append(id_val)
            
            # Build parameterized IN clause
            placeholders = [f":exclude_id_{i}" for i in range(len(validated_ids))]
            exclude_clause = f"AND id NOT IN ({','.join(placeholders)})"
            for i, id_val in enumerate(validated_ids):
                query_params[f"exclude_id_{i}"] = id_val
        
        query = text(f"""
            SELECT 
                id,
                1 - (embedding <=> :embedding::vector) as similarity
            FROM {table}
            WHERE 1 - (embedding <=> :embedding::vector) >= :threshold
            {exclude_clause}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """)
        
        result = await db.execute(
            query,
            {
                "embedding": embedding_str,
                "threshold": threshold,
                "limit": limit,
            }
        )
        
        rows = result.fetchall()
        
        # Convert to list of dicts
        results = []
        for row in rows:
            row_dict = dict(row._mapping)
            results.append(row_dict)
        
        return results
    
    async def upsert_embedding(
        self,
        db: AsyncSession,
        table: str,
        product_id: int,
        embedding: np.ndarray,
        model_name: str,
        text_hash: Optional[str] = None,
    ):
        """
        Upsert embedding for a product.
        
        Args:
            db: Database session
            table: Table name (typically 'product_embeddings')
            product_id: Product ID
            embedding: Embedding vector
            model_name: Model name used to generate embedding
            text_hash: Optional hash of source text
        """
        embedding_list = embedding.tolist()
        embedding_str = "[" + ",".join(map(str, embedding_list)) + "]"
        
        # Use INSERT ... ON CONFLICT for upsert
        query = text(f"""
            INSERT INTO {table} (product_id, embedding, model_name, text_hash, updated_at)
            VALUES (:product_id, :embedding::vector, :model_name, :text_hash, NOW())
            ON CONFLICT (product_id, model_name)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                text_hash = EXCLUDED.text_hash,
                updated_at = NOW()
        """)
        
        await db.execute(
            query,
            {
                "product_id": product_id,
                "embedding": embedding_str,
                "model_name": model_name,
                "text_hash": text_hash,
            }
        )
        await db.commit()
    
    async def batch_upsert_embeddings(
        self,
        db: AsyncSession,
        table: str,
        embeddings: List[dict],
    ):
        """
        Batch upsert multiple embeddings.
        
        Args:
            db: Database session
            table: Table name
            embeddings: List of dicts with keys: product_id, embedding, model_name, text_hash
        """
        if not embeddings:
            return
        
        # Build batch insert query using parameterized placeholders
        # Use executemany with parameterized query to avoid SQL injection
        placeholders = []
        params_list = []
        
        for i, emb in enumerate(embeddings):
            embedding_list = emb["embedding"].tolist() if isinstance(emb["embedding"], np.ndarray) else emb["embedding"]
            placeholders.append(f"(:product_id_{i}, :embedding_{i}::vector, :model_name_{i}, :text_hash_{i}, NOW())")
            params_list.append({
                f"product_id_{i}": emb["product_id"],
                f"embedding_{i}": str(embedding_list),  # Convert to string for vector type
                f"model_name_{i}": emb["model_name"],
                f"text_hash_{i}": emb.get("text_hash", ""),
            })
        
        # Flatten parameters for single execute call
        flat_params = {}
        for params in params_list:
            flat_params.update(params)
        
        query_str = f"""
            INSERT INTO {table} (product_id, embedding, model_name, text_hash, updated_at)
            VALUES {','.join(placeholders)}
            ON CONFLICT (product_id, model_name)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                text_hash = EXCLUDED.text_hash,
                updated_at = NOW()
        """
        
        await db.execute(text(query_str), flat_params)
        await db.commit()
    
    async def get_embedding(
        self,
        db: AsyncSession,
        table: str,
        product_id: int,
        model_name: str,
    ) -> Optional[np.ndarray]:
        """
        Get embedding for a product.
        
        Args:
            db: Database session
            table: Table name
            product_id: Product ID
            model_name: Model name
            
        Returns:
            Embedding vector or None if not found
        """
        query = text(f"""
            SELECT embedding
            FROM {table}
            WHERE product_id = :product_id AND model_name = :model_name
        """)
        
        result = await db.execute(
            query,
            {"product_id": product_id, "model_name": model_name}
        )
        row = result.fetchone()
        
        if row:
            # Convert vector back to numpy array
            embedding_list = row[0]
            return np.array(embedding_list)
        
        return None


# Global vector store instance
vector_store = VectorStore()
