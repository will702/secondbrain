"""embeddings 384 -> 1024 (local-ai Qwen3-Embedding-0.6B)

Existing 384-d vectors are invalid for the new model: they are cleared here
and re-embedded afterwards (scripts/reembed.py; ingestion also re-embeds
chunks whose embedding IS NULL).

Revision ID: 3f7d21ab9c45
Revises: 9b6d51d829fd
Create Date: 2026-09-03
"""

from alembic import op

revision = "3f7d21ab9c45"
down_revision = "9b6d51d829fd"
branch_labels = None
depends_on = None

TABLES = ("document_chunks", "entities", "memories")


def _resize(dim: int) -> None:
    op.drop_index("chunks_embedding_idx", table_name="document_chunks")
    for table in TABLES:
        op.execute(f"UPDATE {table} SET embedding = NULL WHERE embedding IS NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dim})")
    op.create_index(
        "chunks_embedding_idx", "document_chunks", ["embedding"],
        unique=False, postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    _resize(1024)


def downgrade() -> None:
    _resize(384)
