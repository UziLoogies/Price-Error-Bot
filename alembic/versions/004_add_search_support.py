"""Add full-text search support and search indexes

Revision ID: 004_add_search_support
Revises: 36c4b2d3a9f0
Create Date: 2026-01-24 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_add_search_support'
down_revision: Union[str, None] = '36c4b2d3a9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add full-text search support and search optimization indexes."""
    
    # Enable required PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    
    # Add tsvector columns for full-text search
    op.add_column('products', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    op.add_column('store_categories', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    
    # Create search analytics tables
    op.create_table('search_queries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('result_count', sa.Integer(), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('search_suggestions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('field_name', sa.String(length=64), nullable=False),
        sa.Column('suggestion_text', sa.String(length=256), nullable=False),
        sa.Column('frequency', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_used', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'field_name', 'suggestion_text', name='uq_search_suggestions')
    )
    
    # Create GIN indexes for full-text search
    op.create_index('idx_products_search_vector', 'products', ['search_vector'], 
                   postgresql_using='gin')
    op.create_index('idx_categories_search_vector', 'store_categories', ['search_vector'], 
                   postgresql_using='gin')
    
    # Create trigram indexes for fuzzy matching
    op.create_index('idx_products_title_trigram', 'products', [sa.text('title gin_trgm_ops')], 
                   postgresql_using='gin')
    op.create_index('idx_products_sku_trigram', 'products', [sa.text('sku gin_trgm_ops')], 
                   postgresql_using='gin')
    op.create_index('idx_categories_name_trigram', 'store_categories', 
                   [sa.text('category_name gin_trgm_ops')], postgresql_using='gin')
    
    # Create composite indexes for common queries
    op.create_index('idx_products_store_created', 'products', ['store', 'created_at'])
    op.create_index('idx_products_price_range', 'products', ['msrp', 'baseline_price'], 
                   postgresql_where=sa.text('msrp IS NOT NULL'))
    op.create_index('idx_alerts_price_date', 'alerts', ['triggered_price', 'sent_at'])
    op.create_index('idx_categories_store_enabled', 'store_categories', 
                   ['store', 'enabled', 'priority'])
    op.create_index('idx_scan_jobs_status_type_date', 'scan_jobs', 
                   ['status', 'job_type', 'created_at'])
    
    # Create indexes for search analytics
    op.create_index('idx_search_queries_entity_date', 'search_queries', 
                   ['entity_type', 'created_at'])
    op.create_index('idx_search_suggestions_entity_field', 'search_suggestions', 
                   ['entity_type', 'field_name', 'frequency'])
    
    # Create functions and triggers for automatic tsvector updates
    op.execute("""
    CREATE OR REPLACE FUNCTION update_products_search_vector()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.search_vector := 
            setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(NEW.sku, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(NEW.store, '')), 'C');
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
    CREATE OR REPLACE FUNCTION update_categories_search_vector()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.search_vector := 
            setweight(to_tsvector('english', COALESCE(NEW.category_name, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(NEW.store, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(NEW.keywords, '')), 'C');
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    
    # Create triggers
    op.execute("""
    CREATE TRIGGER products_search_vector_update 
        BEFORE INSERT OR UPDATE ON products
        FOR EACH ROW EXECUTE FUNCTION update_products_search_vector();
    """)
    
    op.execute("""
    CREATE TRIGGER categories_search_vector_update 
        BEFORE INSERT OR UPDATE ON store_categories
        FOR EACH ROW EXECUTE FUNCTION update_categories_search_vector();
    """)
    
    # Populate existing search vectors
    op.execute("""
    UPDATE products SET search_vector = 
        setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(sku, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(store, '')), 'C');
    """)
    
    op.execute("""
    UPDATE store_categories SET search_vector = 
        setweight(to_tsvector('english', COALESCE(category_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(store, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(keywords, '')), 'C');
    """)


def downgrade() -> None:
    """Remove search support."""
    
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS products_search_vector_update ON products")
    op.execute("DROP TRIGGER IF EXISTS categories_search_vector_update ON store_categories")
    
    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_products_search_vector()")
    op.execute("DROP FUNCTION IF EXISTS update_categories_search_vector()")
    
    # Drop indexes
    op.drop_index('idx_search_suggestions_entity_field', table_name='search_suggestions')
    op.drop_index('idx_search_queries_entity_date', table_name='search_queries')
    op.drop_index('idx_scan_jobs_status_type_date', table_name='scan_jobs')
    op.drop_index('idx_categories_store_enabled', table_name='store_categories')
    op.drop_index('idx_alerts_price_date', table_name='alerts')
    op.drop_index('idx_products_price_range', table_name='products')
    op.drop_index('idx_products_store_created', table_name='products')
    op.drop_index('idx_categories_name_trigram', table_name='store_categories')
    op.drop_index('idx_products_sku_trigram', table_name='products')
    op.drop_index('idx_products_title_trigram', table_name='products')
    op.drop_index('idx_categories_search_vector', table_name='store_categories')
    op.drop_index('idx_products_search_vector', table_name='products')
    
    # Drop search analytics tables
    op.drop_table('search_suggestions')
    op.drop_table('search_queries')
    
    # Drop tsvector columns
    op.drop_column('store_categories', 'search_vector')
    op.drop_column('products', 'search_vector')
    
    # Note: We don't drop extensions as they might be used by other parts of the system