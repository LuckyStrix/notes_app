"""add diagrams

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-25 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diagrams',
        sa.Column('note_id', sa.UUID(), nullable=False),
        sa.Column('storage_path', sa.String(length=1024), nullable=False),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('source_timestamp', sa.Float(), nullable=True),
        sa.Column('ocr_text', sa.Text(), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='processing', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('processing','ready','error')", name='ck_diagrams_status'),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'diagram_candidates',
        sa.Column('note_id', sa.UUID(), nullable=False),
        sa.Column('storage_path', sa.String(length=1024), nullable=False),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('source_timestamp', sa.Float(), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('note_files', sa.Column('candidate_status', sa.String(length=20), nullable=True))
    op.add_column('note_files', sa.Column('candidate_error', sa.Text(), nullable=True))
    op.add_column('note_files', sa.Column('candidates_generated_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('embedding_chunks', sa.Column('diagram_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_embedding_chunks_diagram_id', 'embedding_chunks', 'diagrams', ['diagram_id'], ['id'], ondelete='CASCADE'
    )
    op.drop_constraint('ck_chunk_source', 'embedding_chunks', type_='check')
    op.create_check_constraint(
        'ck_chunk_source', 'embedding_chunks', "source IN ('note_body','transcript','diagram')"
    )

    op.add_column('citations', sa.Column('diagram_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_citations_diagram_id', 'citations', 'diagrams', ['diagram_id'], ['id'], ondelete='SET NULL'
    )

    # Captioning always goes through a local Ollama vision model regardless
    # of llm_provider -- NULL means "not configured", degrading to OCR-only.
    op.add_column('app_settings', sa.Column('ollama_vision_model', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'ollama_vision_model')

    op.drop_constraint('fk_citations_diagram_id', 'citations', type_='foreignkey')
    op.drop_column('citations', 'diagram_id')

    op.drop_constraint('ck_chunk_source', 'embedding_chunks', type_='check')
    op.create_check_constraint('ck_chunk_source', 'embedding_chunks', "source IN ('note_body','transcript')")
    op.drop_constraint('fk_embedding_chunks_diagram_id', 'embedding_chunks', type_='foreignkey')
    op.drop_column('embedding_chunks', 'diagram_id')

    op.drop_column('note_files', 'candidates_generated_at')
    op.drop_column('note_files', 'candidate_error')
    op.drop_column('note_files', 'candidate_status')

    op.drop_table('diagram_candidates')
    op.drop_table('diagrams')
