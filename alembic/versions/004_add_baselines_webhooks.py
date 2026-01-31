"""Add ProductBaselineCache, NotificationHistory, and enhanced Webhook fields.

Revision ID: 004_add_baselines_webhooks
Revises: 36c4b2d3a9f0
Create Date: 2026-01-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_baselines_webhooks'
down_revision: Union[str, None] = '36c4b2d3a9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create product_baseline_cache table
    op.create_table(
        'product_baseline_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('avg_price_7d', sa.Numeric(10, 2), nullable=True),
        sa.Column('avg_price_30d', sa.Numeric(10, 2), nullable=True),
        sa.Column('min_price_seen', sa.Numeric(10, 2), nullable=False),
        sa.Column('max_price_seen', sa.Numeric(10, 2), nullable=False),
        sa.Column('current_baseline', sa.Numeric(10, 2), nullable=False),
        sa.Column('price_stability', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('std_deviation', sa.Float(), nullable=True),
        sa.Column('observation_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_calculated', sa.DateTime(), nullable=False),
        sa.Column('last_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('last_price_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id')
    )
    op.create_index('ix_product_baseline_cache_product_id', 'product_baseline_cache', ['product_id'])
    
    # Create notification_history table
    op.create_table(
        'notification_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('webhook_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('notification_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.Column('response', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notification_history_webhook_id', 'notification_history', ['webhook_id'])
    op.create_index('ix_notification_history_sent_at', 'notification_history', ['sent_at'])
    
    # Add new columns to webhooks table
    op.add_column('webhooks', sa.Column('webhook_type', sa.String(32), nullable=False, server_default='discord'))
    op.add_column('webhooks', sa.Column('template', sa.Text(), nullable=True))
    op.add_column('webhooks', sa.Column('headers', sa.Text(), nullable=True))
    op.add_column('webhooks', sa.Column('filters', sa.Text(), nullable=True))
    op.add_column('webhooks', sa.Column('telegram_chat_id', sa.String(64), nullable=True))
    op.add_column('webhooks', sa.Column('telegram_bot_token', sa.String(128), nullable=True))
    op.add_column('webhooks', sa.Column('last_sent_at', sa.DateTime(), nullable=True))
    op.add_column('webhooks', sa.Column('send_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('webhooks', sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('webhooks', sa.Column('created_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Drop new webhook columns
    op.drop_column('webhooks', 'created_at')
    op.drop_column('webhooks', 'error_count')
    op.drop_column('webhooks', 'send_count')
    op.drop_column('webhooks', 'last_sent_at')
    op.drop_column('webhooks', 'telegram_bot_token')
    op.drop_column('webhooks', 'telegram_chat_id')
    op.drop_column('webhooks', 'filters')
    op.drop_column('webhooks', 'headers')
    op.drop_column('webhooks', 'template')
    op.drop_column('webhooks', 'webhook_type')
    
    # Drop notification_history table
    op.drop_index('ix_notification_history_sent_at', 'notification_history')
    op.drop_index('ix_notification_history_webhook_id', 'notification_history')
    op.drop_table('notification_history')
    
    # Drop product_baseline_cache table
    op.drop_index('ix_product_baseline_cache_product_id', 'product_baseline_cache')
    op.drop_table('product_baseline_cache')
