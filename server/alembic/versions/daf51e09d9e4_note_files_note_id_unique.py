"""note_files note_id unique

Revision ID: daf51e09d9e4
Revises: c21eda34cc0b
Create Date: 2026-08-24 12:25:22.414037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'daf51e09d9e4'
down_revision: Union[str, None] = 'c21eda34cc0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Note: autogenerate also proposed dropping ix_embedding_chunks_embedding /
    # ix_keywords_embedding here -- those HNSW indexes aren't declared on the
    # ORM models (pgvector index syntax isn't autogenerate-representable the
    # same way), so they always show up as spurious diffs. Left in place
    # intentionally; only the real schema change goes in this migration.
    op.create_unique_constraint(None, 'note_files', ['note_id'])


def downgrade() -> None:
    op.drop_constraint(None, 'note_files', type_='unique')
