"""Re-embed rows whose embedding is NULL after the 384→1024 migration.

Run with the local-ai server up:  uv run python scripts/reembed.py

Batches every table with an embedding column; skips cleanly when nothing is
pending. Safe to re-run.
"""

import math
import sys
import uuid

import sqlalchemy as sa

from app.core.db import engine
from app.agents.embeddings import get_embedder

BATCH = 64

# table -> SQL expression for the text that represents the row
TABLES: dict[str, str] = {
    "document_chunks": "text",
    "entities": "coalesce(name || ' — ' || description, name)",
    "memories": "content",
}


def reembed_table(table: str, text_expr: str) -> int:
    total = 0
    while True:
        with engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    f"SELECT id, {text_expr} AS text FROM {table} "
                    f"WHERE embedding IS NULL LIMIT {BATCH}"
                )
            ).mappings().all()
        if not rows:
            return total
        vectors = get_embedder().embed_texts([r["text"] or "" for r in rows])
        with engine.begin() as conn:
            for row, vector in zip(rows, vectors):
                conn.execute(
                    sa.text(f"UPDATE {table} SET embedding = :vec WHERE id = :id"),
                    {"vec": str(vector), "id": row["id"]},
                )
        total += len(rows)
        print(f"  {table}: embedded {total}")


def main() -> int:
    for table, text_expr in TABLES.items():
        with engine.begin() as conn:
            pending = conn.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE embedding IS NULL")
            ).scalar()
        print(f"{table}: {pending} rows pending")
        if pending:
            reembed_table(table, text_expr)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
