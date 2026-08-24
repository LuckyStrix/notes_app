"""add app_settings app_name

Revision ID: 67bfee6b0f56
Revises: b152b4aabb47
Create Date: 2026-08-24 19:49:01.497567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '67bfee6b0f56'
down_revision: Union[str, None] = 'b152b4aabb47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('app_name', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'app_name')
