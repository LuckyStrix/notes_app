"""add whisper_language setting

Revision ID: a7c9e1f30b52
Revises: c13a3e9c2f89
Create Date: 2026-09-19 21:30:00.000000

Purely additive: one new NOT NULL column with a server default, so every existing
row (the app_settings singleton) is valid immediately and nothing is rewritten.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c9e1f30b52'
down_revision: Union[str, None] = 'c13a3e9c2f89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Whisper's own language auto-detect labelled English lectures as Welsh and
    # produced unusable transcripts, so the language is explicit by default.
    # "auto" opts back in to auto-detection.
    op.add_column(
        'app_settings',
        sa.Column('whisper_language', sa.String(length=8), nullable=False, server_default='en'),
    )
    op.create_check_constraint(
        'ck_app_settings_whisper_language',
        'app_settings',
        "whisper_language = 'auto' OR whisper_language ~ '^[a-z]{2,3}$'",
    )


def downgrade() -> None:
    op.drop_constraint('ck_app_settings_whisper_language', 'app_settings', type_='check')
    op.drop_column('app_settings', 'whisper_language')
