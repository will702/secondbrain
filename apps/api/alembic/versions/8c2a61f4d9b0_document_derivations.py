"""document derivation lineage

Revision ID: 8c2a61f4d9b0
Revises: 3f7d21ab9c45
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "8c2a61f4d9b0"
down_revision = "3f7d21ab9c45"
branch_labels = None
depends_on = None

UUID_PATTERN = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def upgrade() -> None:
    op.drop_constraint("events_task_id_fkey", "events", type_="foreignkey")
    op.create_foreign_key(
        "events_task_id_fkey", "events", "tasks", ["task_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_constraint("deadlines_task_id_fkey", "deadlines", type_="foreignkey")
    op.create_foreign_key(
        "deadlines_task_id_fkey",
        "deadlines",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("commitments_deadline_id_fkey", "commitments", type_="foreignkey")
    op.create_foreign_key(
        "commitments_deadline_id_fkey",
        "commitments",
        "deadlines",
        ["deadline_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "document_derivations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provenance",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "object_type", "object_id", name="uq_document_derivation"
        ),
    )
    op.create_index("ix_document_derivations_document_id", "document_derivations", ["document_id"])
    op.create_index("derivations_object_idx", "document_derivations", ["object_type", "object_id"])

    for table, object_type in (
        ("tasks", "task"),
        ("deadlines", "deadline"),
        ("commitments", "commitment"),
        ("entity_relationships", "relationship"),
        ("review_items", "review"),
    ):
        op.execute(
            f"""
            INSERT INTO document_derivations (document_id, object_type, object_id, provenance)
            SELECT d.id, '{object_type}', source.id, source.provenance
            FROM {table} AS source
            JOIN documents AS d
              ON source.provenance->>'document_id' ~ '{UUID_PATTERN}'
             AND d.id = (source.provenance->>'document_id')::uuid
            ON CONFLICT DO NOTHING
            """
        )

    op.execute(
        """
        INSERT INTO document_derivations (document_id, object_type, object_id, provenance)
        SELECT DISTINCT d.id, 'project', d.project_id,
               jsonb_build_object('document_id', d.id::text, 'extractor', 'migration')
        FROM documents AS d
        WHERE d.project_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO document_derivations (document_id, object_type, object_id, provenance)
        SELECT DISTINCT c.document_id, 'entity', m.entity_id,
               jsonb_build_object('document_id', c.document_id::text,
                                  'chunk_id', c.id::text, 'extractor', 'migration')
        FROM entity_mentions AS m
        JOIN document_chunks AS c ON c.id = m.chunk_id
        ON CONFLICT DO NOTHING
        """
    )

    # Remove facts whose sole recorded source document was deleted before lineage existed.
    for table in ("entity_relationships", "review_items", "commitments"):
        op.execute(
            f"""
            DELETE FROM {table} AS source
            WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
              AND NOT EXISTS (
                SELECT 1 FROM documents d
                WHERE d.id = (source.provenance->>'document_id')::uuid
              )
            """
        )
    op.execute(
        f"""
        UPDATE deadlines SET task_id = NULL
        WHERE task_id IN (
          SELECT source.id FROM tasks source
          WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
            AND NOT EXISTS (
              SELECT 1 FROM documents d
              WHERE d.id = (source.provenance->>'document_id')::uuid
            )
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM events
        WHERE task_id IN (
          SELECT source.id FROM tasks source
          WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
            AND NOT EXISTS (
              SELECT 1 FROM documents d
              WHERE d.id = (source.provenance->>'document_id')::uuid
            )
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM tasks AS source
        WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
          AND NOT EXISTS (
            SELECT 1 FROM documents d
            WHERE d.id = (source.provenance->>'document_id')::uuid
          )
        """
    )
    op.execute(
        f"""
        UPDATE commitments SET deadline_id = NULL
        WHERE deadline_id IN (
          SELECT source.id FROM deadlines source
          WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
            AND NOT EXISTS (
              SELECT 1 FROM documents d
              WHERE d.id = (source.provenance->>'document_id')::uuid
            )
        )
        """
    )
    op.execute(
        f"""
        UPDATE tasks SET deadline_id = NULL
        WHERE deadline_id IN (
          SELECT source.id FROM deadlines source
          WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
            AND NOT EXISTS (
              SELECT 1 FROM documents d
              WHERE d.id = (source.provenance->>'document_id')::uuid
            )
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM deadlines AS source
        WHERE source.provenance->>'document_id' ~ '{UUID_PATTERN}'
          AND NOT EXISTS (
            SELECT 1 FROM documents d
            WHERE d.id = (source.provenance->>'document_id')::uuid
          )
        """
    )


def downgrade() -> None:
    op.drop_index("derivations_object_idx", table_name="document_derivations")
    op.drop_index("ix_document_derivations_document_id", table_name="document_derivations")
    op.drop_table("document_derivations")
    for table, constraint, column, target in (
        ("events", "events_task_id_fkey", "task_id", "tasks"),
        ("deadlines", "deadlines_task_id_fkey", "task_id", "tasks"),
        ("commitments", "commitments_deadline_id_fkey", "deadline_id", "deadlines"),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(constraint, table, target, [column], ["id"])
