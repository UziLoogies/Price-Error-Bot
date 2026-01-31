"""Alter proxy_configs.password column size for encryption.

Revision ID: 006_alter_proxy_password_column
Revises: 005_add_proxy_enhancements
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_alter_proxy_password_column'
down_revision: Union[str, None] = '005_add_proxy_enhancements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alter password column from String(256) to String(512) to accommodate encrypted data
    # Encrypted strings are base64-encoded and require more space
    op.alter_column(
        'proxy_configs',
        'password',
        existing_type=sa.String(256),
        type_=sa.String(512),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Revert password column back to String(256)
    op.alter_column(
        'proxy_configs',
        'password',
        existing_type=sa.String(512),
        type_=sa.String(256),
        existing_nullable=True,
    )
