"""Add scan improvements - ScanJob, ProductExclusion, and enhanced StoreCategory

Revision ID: 003_scan_improvements
Revises: 002_proxy_categories
Create Date: 2026-01-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_scan_improvements'
down_revision: Union[str, None] = '002_proxy_categories'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to store_categories table for scan configuration
    op.add_column('store_categories', sa.Column('max_pages', sa.Integer(), nullable=False, server_default='2'))
    op.add_column('store_categories', sa.Column('scan_interval_minutes', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('store_categories', sa.Column('priority', sa.Integer(), nullable=False, server_default='1'))
    
    # Add filtering configuration columns
    op.add_column('store_categories', sa.Column('keywords', sa.Text(), nullable=True))
    op.add_column('store_categories', sa.Column('exclude_keywords', sa.Text(), nullable=True))
    op.add_column('store_categories', sa.Column('brands', sa.Text(), nullable=True))
    op.add_column('store_categories', sa.Column('min_price', sa.Numeric(10, 2), nullable=True))
    op.add_column('store_categories', sa.Column('max_price', sa.Numeric(10, 2), nullable=True))
    
    # Add deal detection threshold overrides
    op.add_column('store_categories', sa.Column('min_discount_percent', sa.Float(), nullable=True))
    op.add_column('store_categories', sa.Column('msrp_threshold', sa.Float(), nullable=True))
    
    # Create scan_jobs table for progress tracking
    op.create_table(
        'scan_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('products_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deals_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['category_id'], ['store_categories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create index on scan_jobs for faster queries
    op.create_index('ix_scan_jobs_status', 'scan_jobs', ['status'])
    op.create_index('ix_scan_jobs_created_at', 'scan_jobs', ['created_at'])
    
    # Create product_exclusions table
    op.create_table(
        'product_exclusions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store', sa.String(32), nullable=False),
        sa.Column('sku', sa.String(64), nullable=True),
        sa.Column('keyword', sa.String(256), nullable=True),
        sa.Column('brand', sa.String(128), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes on product_exclusions for faster filtering
    op.create_index('ix_product_exclusions_store', 'product_exclusions', ['store'])
    op.create_index('ix_product_exclusions_sku', 'product_exclusions', ['sku'])


def downgrade() -> None:
    # Drop product_exclusions indexes and table
    op.drop_index('ix_product_exclusions_sku', table_name='product_exclusions')
    op.drop_index('ix_product_exclusions_store', table_name='product_exclusions')
    op.drop_table('product_exclusions')
    
    # Drop scan_jobs indexes and table
    op.drop_index('ix_scan_jobs_created_at', table_name='scan_jobs')
    op.drop_index('ix_scan_jobs_status', table_name='scan_jobs')
    op.drop_table('scan_jobs')
    
    # Remove new columns from store_categories
    op.drop_column('store_categories', 'msrp_threshold')
    op.drop_column('store_categories', 'min_discount_percent')
    op.drop_column('store_categories', 'max_price')
    op.drop_column('store_categories', 'min_price')
    op.drop_column('store_categories', 'brands')
    op.drop_column('store_categories', 'exclude_keywords')
    op.drop_column('store_categories', 'keywords')
    op.drop_column('store_categories', 'priority')
    op.drop_column('store_categories', 'scan_interval_minutes')
    op.drop_column('store_categories', 'max_pages')
