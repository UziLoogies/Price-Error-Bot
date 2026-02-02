"""Add session metadata fields to StoreCategory

Revision ID: a1b2c3d4e5f6
Revises: 003_scan_improvements
Create Date: 2024-01-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '003_scan_improvements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add cooldown_until field to store_categories
    op.add_column('store_categories', sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=True))
    
    # Add broken_url field to store_categories
    op.add_column('store_categories', sa.Column('broken_url', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Remove broken_url field
    op.drop_column('store_categories', 'broken_url')
    
    # Remove cooldown_until field
    op.drop_column('store_categories', 'cooldown_until')
