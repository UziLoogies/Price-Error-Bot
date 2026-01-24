"""Add proxy configuration and store category tables

Revision ID: 002_proxy_categories
Revises: 001_initial
Create Date: 2026-01-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_proxy_categories'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create proxy_configs table
    op.create_table(
        'proxy_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('host', sa.String(256), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(128), nullable=True),
        sa.Column('password', sa.String(256), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_used', sa.DateTime(), nullable=True),
        sa.Column('last_success', sa.DateTime(), nullable=True),
        sa.Column('failure_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create store_categories table
    op.create_table(
        'store_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store', sa.String(32), nullable=False),
        sa.Column('category_name', sa.String(128), nullable=False),
        sa.Column('category_url', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_scanned', sa.DateTime(), nullable=True),
        sa.Column('products_found', sa.Integer(), nullable=False, default=0),
        sa.Column('deals_found', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store', 'category_url', name='uq_store_category_url')
    )

    # Add original_price column to price_history table
    op.add_column(
        'price_history',
        sa.Column('original_price', sa.Numeric(10, 2), nullable=True)
    )


def downgrade() -> None:
    # Remove original_price column from price_history
    op.drop_column('price_history', 'original_price')

    # Drop store_categories table
    op.drop_table('store_categories')

    # Drop proxy_configs table
    op.drop_table('proxy_configs')
