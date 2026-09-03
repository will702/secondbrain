"""Pydantic schemas for LLM structured output — the validation wall between
model output and the database (AI_SYSTEM.md §3)."""

from pydantic import BaseModel, Field


class DocumentProfile(BaseModel):
    doc_kind: str = "other"
    title: str = ""
    topic: str = ""
    importance: float = Field(default=0.3, ge=0.0, le=1.0)
    summary: str = ""


class ExtractedDate(BaseModel):
    quote: str = Field(min_length=3)
    when_text: str = Field(min_length=1)
    kind: str = "other"  # deadline | event | course_session | recurrence | other
    title: str = ""
    explicit: bool = False


class ExtractedDates(BaseModel):
    dates: list[ExtractedDate] = Field(default_factory=list, max_length=30)


class ExtractedTask(BaseModel):
    quote: str = Field(min_length=3)
    title: str = Field(min_length=2)
    estimated_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    when_text: str = ""


class ExtractedCommitment(BaseModel):
    quote: str = Field(min_length=3)
    text: str
    direction: str = "user_promised"
    confidence: str = "possible"  # confirmed | likely | possible
    when_text: str = ""


class ExtractedTasks(BaseModel):
    tasks: list[ExtractedTask] = Field(default_factory=list, max_length=30)
    commitments: list[ExtractedCommitment] = Field(default_factory=list, max_length=30)


class ExtractedEntityRef(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "topic"


class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str
    quote: str = Field(min_length=3)


class ExtractedEntities(BaseModel):
    entities: list[ExtractedEntityRef] = Field(default_factory=list, max_length=40)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=40)
