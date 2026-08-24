"""allow document note type

Revision ID: b152b4aabb47
Revises: daf51e09d9e4
Create Date: 2026-08-24 13:19:35.878527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b152b4aabb47'
down_revision: Union[str, None] = 'daf51e09d9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_notes_type', 'notes', type_='check')
    op.create_check_constraint('ck_notes_type', 'notes', "type IN ('text','audio','video','document')")


def downgrade() -> None:
    op.drop_constraint('ck_notes_type', 'notes', type_='check')
    op.create_check_constraint('ck_notes_type', 'notes', "type IN ('text','audio','video')")
