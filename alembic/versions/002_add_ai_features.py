"""Add AI features

Revision ID: 002_add_ai_features
Revises: 001_initial
Create Date: 2024-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_add_ai_features'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Add columns to products table
    op.add_column('products', sa.Column('structured_attributes', postgresql.JSONB, nullable=True))
    op.add_column('products', sa.Column('llm_reviewed', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('products', sa.Column('llm_review_at', sa.DateTime(), nullable=True))
    # Note: embedding_vector will be added via pgvector, but we'll add it as a regular column first
    # The actual vector type will be handled by pgvector extension
    
    # Create product_embeddings table
    op.create_table(
        'product_embeddings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=False),  # 768-D vector
        sa.Column('model_name', sa.String(length=128), nullable=False),
        sa.Column('text_hash', sa.String(length=64), nullable=True),  # Hash of source text for caching
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('product_id', 'model_name', name='uq_product_embedding_model')
    )
    
    # Create product_attributes table
    op.create_table(
        'product_attributes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('brand', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=256), nullable=True),
        sa.Column('size', sa.String(length=64), nullable=True),
        sa.Column('color', sa.String(length=64), nullable=True),
        sa.Column('category', sa.String(length=128), nullable=True),
        sa.Column('extracted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('extraction_method', sa.String(length=32), nullable=True),  # 'ner', 'llm', 'rule'
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('raw_attributes', postgresql.JSONB, nullable=True),  # Full extracted attributes as JSON
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('product_id', name='uq_product_attributes')
    )
    
    # Create product_matches table
    op.create_table(
        'product_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id_1', sa.Integer(), nullable=False),
        sa.Column('product_id_2', sa.Integer(), nullable=False),
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('match_method', sa.String(length=32), nullable=False),  # 'embedding', 'manual', 'rule'
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id_1'], ['products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id_2'], ['products.id'], ondelete='CASCADE'),
        sa.CheckConstraint('product_id_1 < product_id_2', name='check_product_order'),
        sa.UniqueConstraint('product_id_1', 'product_id_2', name='uq_product_match')
    )
    
    # Create llm_feedback table
    op.create_table(
        'llm_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('llm_output', postgresql.JSONB, nullable=False),
        sa.Column('user_correction', postgresql.JSONB, nullable=True),
        sa.Column('task_type', sa.String(length=64), nullable=False),  # 'anomaly_review', 'attribute_extraction', etc.
        sa.Column('prompt_hash', sa.String(length=64), nullable=True),
        sa.Column('model_name', sa.String(length=128), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('feedback_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL')
    )
    
    # Create indexes
    op.create_index('ix_product_embeddings_product_id', 'product_embeddings', ['product_id'])
    op.create_index('ix_product_embeddings_model_name', 'product_embeddings', ['model_name'])
    op.create_index('ix_product_attributes_product_id', 'product_attributes', ['product_id'])
    op.create_index('ix_product_attributes_brand', 'product_attributes', ['brand'])
    op.create_index('ix_product_attributes_category', 'product_attributes', ['category'])
    op.create_index('ix_product_matches_product_id_1', 'product_matches', ['product_id_1'])
    op.create_index('ix_product_matches_product_id_2', 'product_matches', ['product_id_2'])
    op.create_index('ix_product_matches_similarity_score', 'product_matches', ['similarity_score'])
    op.create_index('ix_product_matches_is_confirmed', 'product_matches', ['is_confirmed'])
    op.create_index('ix_llm_feedback_product_id', 'llm_feedback', ['product_id'])
    op.create_index('ix_llm_feedback_task_type', 'llm_feedback', ['task_type'])
    op.create_index('ix_llm_feedback_created_at', 'llm_feedback', ['created_at'])
    
    # Create GIN index for JSONB columns for faster queries
    op.execute('CREATE INDEX ix_products_structured_attributes ON products USING GIN (structured_attributes)')
    op.execute('CREATE INDEX ix_product_attributes_raw_attributes ON product_attributes USING GIN (raw_attributes)')
    op.execute('CREATE INDEX ix_llm_feedback_llm_output ON llm_feedback USING GIN (llm_output)')
    
    # Note: Vector index for embeddings will be created separately after pgvector is confirmed working
    # This will be done via: CREATE INDEX ON product_embeddings USING ivfflat (embedding vector_cosine_ops);


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_llm_feedback_created_at', table_name='llm_feedback')
    op.drop_index('ix_llm_feedback_task_type', table_name='llm_feedback')
    op.drop_index('ix_llm_feedback_product_id', table_name='llm_feedback')
    op.drop_index('ix_product_matches_is_confirmed', table_name='product_matches')
    op.drop_index('ix_product_matches_similarity_score', table_name='product_matches')
    op.drop_index('ix_product_matches_product_id_2', table_name='product_matches')
    op.drop_index('ix_product_matches_product_id_1', table_name='product_matches')
    op.drop_index('ix_product_attributes_category', table_name='product_attributes')
    op.drop_index('ix_product_attributes_brand', table_name='product_attributes')
    op.drop_index('ix_product_attributes_product_id', table_name='product_attributes')
    op.drop_index('ix_product_embeddings_model_name', table_name='product_embeddings')
    op.drop_index('ix_product_embeddings_product_id', table_name='product_embeddings')
    
    # Drop GIN indexes
    op.execute('DROP INDEX IF EXISTS ix_llm_feedback_llm_output')
    op.execute('DROP INDEX IF EXISTS ix_product_attributes_raw_attributes')
    op.execute('DROP INDEX IF EXISTS ix_products_structured_attributes')
    
    # Drop tables
    op.drop_table('llm_feedback')
    op.drop_table('product_matches')
    op.drop_table('product_attributes')
    op.drop_table('product_embeddings')
    
    # Drop columns from products table
    op.drop_column('products', 'llm_review_at')
    op.drop_column('products', 'llm_reviewed')
    op.drop_column('products', 'structured_attributes')
    
    # Note: pgvector extension is not dropped as it may be used by other databases
