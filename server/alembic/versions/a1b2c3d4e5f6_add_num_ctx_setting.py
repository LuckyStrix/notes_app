"""add num_ctx setting

Revision ID: a1b2c3d4e5f6
Revises: ffc0b25f440e
Create Date: 2026-08-25 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ffc0b25f440e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ollama's own default when no options.num_ctx is passed is 2048 tokens --
    # silently truncating RAG context + chat history. 8192 is a safer default
    # that still fits comfortably on most local GPUs running a ~14B model.
    op.add_column(
        'app_settings',
        sa.Column('num_ctx', sa.Integer(), nullable=False, server_default='8192'),
    )
    op.create_check_constraint('ck_app_settings_num_ctx', 'app_settings', 'num_ctx > 0')


def downgrade() -> None:
    op.drop_constraint('ck_app_settings_num_ctx', 'app_settings', type_='check')
    op.drop_column('app_settings', 'num_ctx')
