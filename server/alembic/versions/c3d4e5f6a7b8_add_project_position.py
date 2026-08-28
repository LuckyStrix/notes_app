"""add project position

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-25 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))

    # server_default alone leaves every existing row tied at 0 -- backfill
    # distinct increasing positions by creation order so the home page's
    # initial ordering matches what users already see today.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE projects SET position = sub.rn
            FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) - 1 AS rn FROM projects) sub
            WHERE projects.id = sub.id
            """
        )
    )


def downgrade() -> None:
    op.drop_column('projects', 'position')
