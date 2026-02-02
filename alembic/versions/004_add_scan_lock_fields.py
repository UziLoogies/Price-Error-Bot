"""Add scan lock fields to ScanJob

Revision ID: 004_add_scan_lock_fields
Revises: 003_add_session_metadata
Create Date: 2024-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_add_scan_lock_fields'
down_revision = '003_add_session_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add run_id field to scan_jobs
    op.add_column('scan_jobs', sa.Column('run_id', sa.String(64), nullable=True))
    
    # Add trigger field to scan_jobs
    op.add_column('scan_jobs', sa.Column('trigger', sa.String(32), nullable=True))
    
    # Create index on run_id for fast lookups
    op.create_index('ix_scan_jobs_run_id', 'scan_jobs', ['run_id'])


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_scan_jobs_run_id', table_name='scan_jobs')
    
    # Remove trigger field
    op.drop_column('scan_jobs', 'trigger')
    
    # Remove run_id field
    op.drop_column('scan_jobs', 'run_id')
