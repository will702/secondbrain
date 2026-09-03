"""Ingestion pipeline: parse → chunk → embed → (extract, added in M2) → processed.

Each stage is idempotent so a retried job resumes where it stopped:
- parse+chunk+embed is checkpointed by existing chunk rows (re-embed only nulls)
- extraction checkpoint: documents.provenance['extraction_done'] (M2)
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.agents.embeddings import get_embedder
from app.models import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.services.parsing import ParseError, parse_bytes
from app.services.parsing.dispatcher import EXTENSIONS
from app.services.storage import Storage

logger = logging.getLogger("secondbrain.ingestion")

EMBED_BATCH = 32


class PipelineError(Exception):
    pass


def _load_document(db: OrmSession, document_id: UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise PipelineError(f"document {document_id} not found")
    return document


def ingest_document(db: OrmSession, document_id: UUID, run_extraction: bool = True) -> Document:
    document = _load_document(db, document_id)
    storage = Storage()

    if document.status == DocumentStatus.processed:
        return document  # already done (idempotent retry)

    # --- Stage 1: parse + chunk + embed ---
    chunks = (
        db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
        .scalars()
        .all()
    )

    if not chunks:
        document.status = DocumentStatus.parsing
        db.commit()
        try:
            data = storage.open(document.storage_path)
            parsed = parse_bytes(data, document.original_filename, document.mime_type)
        except ParseError as exc:
            # Permanent failure: record it on the document and finish the job —
            # retrying a broken file would never succeed.
            document.status = DocumentStatus.failed
            document.error = str(exc)
            db.commit()
            return document

        from app.services.ingestion.chunker import chunk_document

        chunk_rows = chunk_document(parsed)
        if not chunk_rows:
            document.status = DocumentStatus.failed
            document.error = "No parsable text found in document"
            db.commit()
            return document

        document.page_count = parsed.page_count
        document.title = document.title or (
            parsed.sections[0].title if parsed.sections else document.original_filename
        )
        document.status = DocumentStatus.embedding
        for chunk in chunk_rows:
            db.add(
                DocumentChunk(
                    user_id=document.user_id,
                    document_id=document.id,
                    chunk_index=chunk["chunk_index"],
                    section=chunk["section"],
                    page=chunk["page"],
                    text=chunk["text"],
                    token_count=chunk["token_count"],
                )
            )
        db.commit()
        chunks = (
            db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
            .scalars()
            .all()
        )

    # Embed any chunks without vectors (resume-safe).
    missing = [c for c in chunks if c.embedding is None]
    if missing:
        embedder = get_embedder()
        for start in range(0, len(missing), EMBED_BATCH):
            batch = missing[start : start + EMBED_BATCH]
            vectors = embedder.embed_texts([c.text for c in batch])
            for chunk_row, vector in zip(batch, vectors, strict=True):
                chunk_row.embedding = vector
        db.commit()
        logger.info("embedded %d chunks", len(missing), extra={"document_id": str(document_id)})

    # --- Stage 2: extraction (M2) ---
    if run_extraction:
        from app.services.ingestion.extract_stage import run_extraction_stage

        run_extraction_stage(db, document, chunks)

    if document.status != DocumentStatus.review:
        document.status = DocumentStatus.processed
        from datetime import UTC, datetime

        document.processed_at = datetime.now(UTC)
    db.commit()
    return document


def supported_extension(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in EXTENSIONS
