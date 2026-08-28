"""add graph summary generation

Revision ID: c13a3e9c2f89
Revises: e5f6a7b8c9d0
Create Date: 2026-08-26 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c13a3e9c2f89'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('keywords', 'keyword_edges'):
        op.add_column(table, sa.Column('basic_summary', sa.Text(), nullable=True))
        op.add_column(table, sa.Column('basic_summary_citations', sa.JSON(), nullable=True))
        op.add_column(table, sa.Column('basic_summary_generated_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column('quality_summary', sa.Text(), nullable=True))
        op.add_column(table, sa.Column('quality_summary_citations', sa.JSON(), nullable=True))
        op.add_column(table, sa.Column('quality_summary_generated_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        'projects',
        sa.Column('summary_generation_status', sa.String(20), nullable=False, server_default='idle'),
    )
    op.add_column('projects', sa.Column('summary_generation_error', sa.Text(), nullable=True))
    op.add_column(
        'projects',
        sa.Column('summary_generation_progress', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'projects',
        sa.Column('summary_generation_total', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_check_constraint(
        'ck_projects_summary_generation_status',
        'projects',
        "summary_generation_status IN ('idle','processing','ready','error')",
    )

    op.add_column('app_settings', sa.Column('ollama_fast_model', sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'ollama_fast_model')

    op.drop_constraint('ck_projects_summary_generation_status', 'projects', type_='check')
    op.drop_column('projects', 'summary_generation_total')
    op.drop_column('projects', 'summary_generation_progress')
    op.drop_column('projects', 'summary_generation_error')
    op.drop_column('projects', 'summary_generation_status')

    for table in ('keywords', 'keyword_edges'):
        op.drop_column(table, 'quality_summary_generated_at')
        op.drop_column(table, 'quality_summary_citations')
        op.drop_column(table, 'quality_summary')
        op.drop_column(table, 'basic_summary_generated_at')
        op.drop_column(table, 'basic_summary_citations')
        op.drop_column(table, 'basic_summary')
