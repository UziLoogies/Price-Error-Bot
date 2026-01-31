"""Add proxy type classification and health tracking.

Revision ID: 005_add_proxy_enhancements
Revises: 004_add_baselines_webhooks
Create Date: 2026-01-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_proxy_enhancements'
down_revision: Union[str, None] = '004_add_baselines_webhooks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add proxy type classification fields
    op.add_column('proxy_configs', sa.Column('proxy_type', sa.String(32), nullable=False, server_default='datacenter'))
    op.add_column('proxy_configs', sa.Column('provider', sa.String(128), nullable=True))
    op.add_column('proxy_configs', sa.Column('region', sa.String(64), nullable=True))
    op.add_column('proxy_configs', sa.Column('cost_per_gb', sa.Float(), nullable=True))
    
    # Add health tracking fields
    op.add_column('proxy_configs', sa.Column('success_rate', sa.Float(), nullable=False, server_default='1.0'))
    op.add_column('proxy_configs', sa.Column('avg_latency_ms', sa.Float(), nullable=False, server_default='0.0'))


def downgrade() -> None:
    # Remove proxy type fields
    op.drop_column('proxy_configs', 'avg_latency_ms')
    op.drop_column('proxy_configs', 'success_rate')
    op.drop_column('proxy_configs', 'cost_per_gb')
    op.drop_column('proxy_configs', 'region')
    op.drop_column('proxy_configs', 'provider')
    op.drop_column('proxy_configs', 'proxy_type')
