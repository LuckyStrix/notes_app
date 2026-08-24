"""add notes search_vector

Revision ID: 60712ad69896
Revises: f30371ef31ca
Create Date: 2026-08-24 19:54:24.215095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '60712ad69896'
down_revision: Union[str, None] = 'f30371ef31ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notes', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))
    op.create_index('ix_notes_search_vector', 'notes', ['search_vector'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_notes_search_vector', table_name='notes')
    op.drop_column('notes', 'search_vector')
