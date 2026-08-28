"""add project graph status

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-25 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tracks the async keyword-graph rebuild job, mirroring Note.status, so
    # the client can poll for completion instead of guessing a duration.
    op.add_column('projects', sa.Column('graph_status', sa.String(length=20), nullable=False, server_default='ready'))
    op.add_column('projects', sa.Column('graph_error', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('graph_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        'ck_projects_graph_status', 'projects', "graph_status IN ('ready','processing','error')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_projects_graph_status', 'projects', type_='check')
    op.drop_column('projects', 'graph_updated_at')
    op.drop_column('projects', 'graph_error')
    op.drop_column('projects', 'graph_status')
