"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Products table
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=False),
        sa.Column('store', sa.String(length=32), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('msrp', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('baseline_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sku', 'store', name='uq_product_sku_store')
    )

    # Price history table
    op.create_table(
        'price_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('shipping', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('availability', sa.String(length=32), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], )
    )

    # Rules table
    op.create_table(
        'rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('rule_type', sa.String(length=32), nullable=False),
        sa.Column('threshold', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Alerts table
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=False),
        sa.Column('triggered_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('previous_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('discord_message_id', sa.String(length=64), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['rule_id'], ['rules.id'])
    )

    # Webhooks table
    op.create_table(
        'webhooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_price_history_product_id', 'price_history', ['product_id'])
    op.create_index('ix_price_history_fetched_at', 'price_history', ['fetched_at'])
    op.create_index('ix_alerts_product_id', 'alerts', ['product_id'])
    op.create_index('ix_alerts_sent_at', 'alerts', ['sent_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_alerts_sent_at', table_name='alerts')
    op.drop_index('ix_alerts_product_id', table_name='alerts')
    op.drop_index('ix_price_history_fetched_at', table_name='price_history')
    op.drop_index('ix_price_history_product_id', table_name='price_history')

    # Drop tables
    op.drop_table('webhooks')
    op.drop_table('alerts')
    op.drop_table('rules')
    op.drop_table('price_history')
    op.drop_table('products')
