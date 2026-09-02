import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.api.schemas import UploadResult
from app.core.config import get_settings
from app.core.db import get_db
from app.models import AuditLog, Document, User
from app.services.ingestion.pipeline import supported_extension
from app.services.storage import Storage
from app.workers.queue import enqueue

logger = logging.getLogger("secondbrain.inbox")

router = APIRouter(prefix="/inbox", tags=["inbox"])

MAX_FILE_BYTES = get_settings().max_upload_mb * 1024 * 1024


@router.post("/upload", response_model=list[UploadResult], status_code=status.HTTP_201_CREATED)
async def upload(
    files: list[UploadFile],
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files provided")
    settings = get_settings()
    storage = Storage()
    results: list[UploadResult] = []

    for upload_file in files:
        filename = upload_file.filename or "unnamed"
        if not supported_extension(filename):
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"Unsupported file type: {filename}",
            )
        data = await upload_file.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"{filename} exceeds {settings.max_upload_mb}MB limit",
            )
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{filename} is empty")

        sha256, path = storage.save(user.id, data)
        existing = db.execute(
            select(Document).where(Document.user_id == user.id, Document.sha256 == sha256)
        ).scalar_one_or_none()
        if existing is not None:
            results.append(
                UploadResult(document_id=existing.id, filename=filename, duplicate=True)
            )
            continue

        document = Document(
            user_id=user.id,
            sha256=sha256,
            original_filename=filename,
            storage_path=str(path),
            mime_type=upload_file.content_type or "application/octet-stream",
        )
        db.add(document)
        db.flush()
        enqueue(
            db,
            "ingest_document",
            {"document_id": str(document.id)},
            user_id=user.id,
            idempotency_key=f"ingest-{document.id}",
        )
        db.add(
            AuditLog(
                user_id=user.id,
                actor="user",
                action="document.upload",
                object_type="document",
                object_id=str(document.id),
                detail={"filename": filename, "sha256": sha256[:16]},
            )
        )
        results.append(UploadResult(document_id=document.id, filename=filename))
    db.commit()
    return results
