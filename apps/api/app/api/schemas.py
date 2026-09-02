import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import DocumentKind, DocumentStatus


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: str = "Asia/Jakarta"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    timezone: str
    autonomy_level: int
    work_hours: dict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    mime_type: str
    doc_kind: DocumentKind
    title: str | None
    topic: str | None
    summary: str | None
    importance: float | None
    status: DocumentStatus
    error: str | None
    page_count: int | None
    chunk_count: int = 0
    created_at: datetime
    processed_at: datetime | None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    section: str | None
    page: int | None
    text: str
    token_count: int


class UploadResult(BaseModel):
    document_id: uuid.UUID
    filename: str
    duplicate: bool = False
