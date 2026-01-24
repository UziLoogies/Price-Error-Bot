"""add_store_category_last_error

Revision ID: 36c4b2d3a9f0
Revises: 35f69e7a29a3
Create Date: 2026-01-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "36c4b2d3a9f0"
down_revision: Union[str, Sequence[str], None] = "35f69e7a29a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("store_categories", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("store_categories", sa.Column("last_error_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("store_categories", "last_error_at")
    op.drop_column("store_categories", "last_error")
