"""add citation page and confidence fields

Revision ID: f30371ef31ca
Revises: 67bfee6b0f56
Create Date: 2026-08-24 19:52:00.088865

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f30371ef31ca'
down_revision: Union[str, None] = '67bfee6b0f56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('embedding_chunks', sa.Column('page_start', sa.Integer(), nullable=True))
    op.add_column('embedding_chunks', sa.Column('page_end', sa.Integer(), nullable=True))
    op.add_column('citations', sa.Column('page_start', sa.Integer(), nullable=True))
    op.add_column('citations', sa.Column('page_end', sa.Integer(), nullable=True))
    op.add_column('citations', sa.Column('confidence', sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column('citations', 'confidence')
    op.drop_column('citations', 'page_end')
    op.drop_column('citations', 'page_start')
    op.drop_column('embedding_chunks', 'page_end')
    op.drop_column('embedding_chunks', 'page_start')
