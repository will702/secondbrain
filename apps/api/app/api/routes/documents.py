import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.api.schemas import ChunkOut, DocumentOut
from app.core.db import get_db
from app.models import Document, DocumentChunk, User

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_owned_document(db: OrmSession, user: User, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
):
    chunk_count = (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Document, chunk_count.label("chunk_count"))
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .limit(min(limit, 500))
        .offset(offset)
    ).all()
    out = []
    for document, count in rows:
        item = DocumentOut.model_validate(document)
        item.chunk_count = count
        out.append(item)
    return out


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    document = _get_owned_document(db, user, document_id)
    out = DocumentOut.model_validate(document)
    out.chunk_count = (
        db.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_id == document.id
            )
        ).scalar()
        or 0
    )
    return out


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def get_document_chunks(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    document = _get_owned_document(db, user, document_id)
    return (
        db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
        )
        .scalars()
        .all()
    )


@router.get("/{document_id}/file")
def get_document_file(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    document = _get_owned_document(db, user, document_id)
    path = Path(document.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "File no longer stored")
    return FileResponse(
        path,
        filename=document.original_filename,
        media_type=document.mime_type or "application/octet-stream",
    )
