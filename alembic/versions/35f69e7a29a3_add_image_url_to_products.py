"""add_image_url_to_products

Revision ID: 35f69e7a29a3
Revises: 003_scan_improvements
Create Date: 2026-01-19 15:53:50.555148

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35f69e7a29a3'
down_revision: Union[str, Sequence[str], None] = '003_scan_improvements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add image_url column to products table
    op.add_column('products', sa.Column('image_url', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove image_url column from products table
    op.drop_column('products', 'image_url')
