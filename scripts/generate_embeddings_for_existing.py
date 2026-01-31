"""Backfill embeddings for existing products."""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.product_matcher import product_matcher
from src.config import settings
from src.db.models import Product
from src.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_embeddings_for_existing(
    batch_size: int = 100,
    limit: Optional[int] = None,
):
    """
    Generate and store embeddings for all existing products.
    
    Args:
        batch_size: Number of products to process in each batch
        limit: Optional limit on total number of products to process
    """
    if not settings.vector_db_enabled or not settings.ai_product_matching_enabled:
        logger.warning("Vector DB or product matching is disabled. Skipping embedding generation.")
        return
    
    logger.info("Starting embedding generation for existing products...")
    
    async with AsyncSessionLocal() as db:
        # Get all products
        query = select(Product).where(Product.title.isnot(None))
        if limit:
            query = query.limit(limit)
        
        result = await db.execute(query)
        all_products = result.scalars().all()
        
        total = len(all_products)
        logger.info(f"Found {total} products to process")
        
        if total == 0:
            logger.info("No products to process")
            return
        
        # Process in batches
        processed = 0
        failed = 0
        
        for i in range(0, total, batch_size):
            batch = all_products[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} products)")
            
            try:
                # Generate embeddings in batch
                await product_matcher.batch_update_embeddings(
                    db=db,
                    products=batch,
                )
                
                processed += len(batch)
                logger.info(f"Processed {processed}/{total} products")
                
            except Exception as e:
                logger.error(f"Failed to process batch {batch_num}: {e}")
                failed += len(batch)
        
        logger.info(
            f"Embedding generation complete: {processed} processed, {failed} failed "
            f"out of {total} total products"
        )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate embeddings for existing products")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of products to process per batch (default: 100)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of products to process (default: all)",
    )
    
    args = parser.parse_args()
    
    asyncio.run(generate_embeddings_for_existing(
        batch_size=args.batch_size,
        limit=args.limit,
    ))
