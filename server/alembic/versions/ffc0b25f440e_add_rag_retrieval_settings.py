"""add rag retrieval settings

Revision ID: ffc0b25f440e
Revises: 60712ad69896
Create Date: 2026-08-25 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ffc0b25f440e'
down_revision: Union[str, None] = '60712ad69896'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_settings',
        sa.Column('default_rag_top_k', sa.Integer(), nullable=False, server_default='6'),
    )
    op.add_column(
        'app_settings',
        sa.Column('default_rag_similarity_floor', sa.Float(), nullable=False, server_default='0.35'),
    )
    op.create_check_constraint(
        'ck_app_settings_default_rag_top_k', 'app_settings', 'default_rag_top_k > 0'
    )
    op.create_check_constraint(
        'ck_app_settings_default_rag_similarity_floor',
        'app_settings',
        'default_rag_similarity_floor >= 0 AND default_rag_similarity_floor <= 1',
    )

    # Per-project overrides -- NULL means "inherit the app_settings default" above.
    op.add_column('projects', sa.Column('rag_top_k', sa.Integer(), nullable=True))
    op.add_column('projects', sa.Column('rag_similarity_floor', sa.Float(), nullable=True))
    op.create_check_constraint(
        'ck_projects_rag_top_k', 'projects', 'rag_top_k IS NULL OR rag_top_k > 0'
    )
    op.create_check_constraint(
        'ck_projects_rag_similarity_floor',
        'projects',
        'rag_similarity_floor IS NULL OR (rag_similarity_floor >= 0 AND rag_similarity_floor <= 1)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_projects_rag_similarity_floor', 'projects', type_='check')
    op.drop_constraint('ck_projects_rag_top_k', 'projects', type_='check')
    op.drop_column('projects', 'rag_similarity_floor')
    op.drop_column('projects', 'rag_top_k')

    op.drop_constraint('ck_app_settings_default_rag_similarity_floor', 'app_settings', type_='check')
    op.drop_constraint('ck_app_settings_default_rag_top_k', 'app_settings', type_='check')
    op.drop_column('app_settings', 'default_rag_similarity_floor')
    op.drop_column('app_settings', 'default_rag_top_k')
