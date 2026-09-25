"""add backup settings

Revision ID: b8d4f21ac907
Revises: a7c9e1f30b52
Create Date: 2026-09-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d4f21ac907'
down_revision: Union[str, None] = 'a7c9e1f30b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('backup_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'app_settings',
        sa.Column('backup_frequency', sa.String(length=16), nullable=False, server_default='daily'),
    )
    op.add_column(
        'app_settings',
        sa.Column('backup_keep', sa.Integer(), nullable=False, server_default='7'),
    )
    op.create_check_constraint(
        'ck_app_settings_backup_frequency', 'app_settings', "backup_frequency IN ('daily','weekly')"
    )
    op.create_check_constraint('ck_app_settings_backup_keep', 'app_settings', 'backup_keep > 0')


def downgrade() -> None:
    op.drop_constraint('ck_app_settings_backup_keep', 'app_settings', type_='check')
    op.drop_constraint('ck_app_settings_backup_frequency', 'app_settings', type_='check')
    op.drop_column('app_settings', 'backup_keep')
    op.drop_column('app_settings', 'backup_frequency')
    op.drop_column('app_settings', 'backup_enabled')
