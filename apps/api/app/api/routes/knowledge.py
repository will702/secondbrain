import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import (
    AIDecision,
    Commitment,
    Deadline,
    Entity,
    EntityMention,
    EntityRelationship,
    Project,
    ReviewItem,
    Task,
    User,
)
from app.models.enums import ReviewStatus

router = APIRouter(tags=["intelligence"])


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    name: str
    description: str | None
    aliases: list
    confidence: float


class RelationOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    predicate: str
    object_id: uuid.UUID
    object_name: str
    confidence: float
    provenance: dict


class GraphOut(BaseModel):
    entities: list[EntityOut]
    relations: list[RelationOut]
    projects: list[dict]


@router.get("/graph", response_model=GraphOut)
def knowledge_graph(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    entities = (
        db.execute(
            select(Entity).where(Entity.user_id == user.id).order_by(Entity.kind, Entity.name)
        )
        .scalars()
        .all()
    )
    relations = (
        db.execute(select(EntityRelationship).where(EntityRelationship.user_id == user.id))
        .scalars()
        .all()
    )
    name_by_id = {e.id: e.name for e in entities}
    projects = db.execute(select(Project).where(Project.user_id == user.id)).scalars().all()
    return GraphOut(
        entities=[EntityOut.model_validate(e) for e in entities],
        relations=[
            RelationOut(
                id=r.id,
                subject_id=r.subject_entity_id,
                subject_name=name_by_id.get(r.subject_entity_id, "?"),
                predicate=r.predicate,
                object_id=r.object_entity_id,
                object_name=name_by_id.get(r.object_entity_id, "?"),
                confidence=r.confidence,
                provenance=r.provenance,
            )
            for r in relations
        ],
        projects=[
            {"id": p.id, "name": p.name, "kind": p.kind, "entity_id": str(p.entity_id)}
            for p in projects
        ],
    )


@router.get("/entities/{entity_id}")
def entity_detail(
    entity_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    entity = db.get(Entity, entity_id)
    if entity is None or entity.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    mentions = (
        db.execute(select(EntityMention).where(EntityMention.entity_id == entity.id).limit(200))
        .scalars()
        .all()
    )
    relations = (
        db.execute(
            select(EntityRelationship).where(
                (EntityRelationship.subject_entity_id == entity.id)
                | (EntityRelationship.object_entity_id == entity.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        **EntityOut.model_validate(entity).model_dump(),
        "mention_count": len(mentions),
        "relations": [
            {
                "predicate": r.predicate,
                "direction": "out" if r.subject_entity_id == entity.id else "in",
                "confidence": r.confidence,
                "provenance": r.provenance,
            }
            for r in relations
        ],
    }


class DeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    normalized_at: object
    date_is_exact: bool
    raw_expression: str
    confidence: float
    explicit: bool
    status: str
    provenance: dict


@router.get("/deadlines", response_model=list[DeadlineOut])
def list_deadlines(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return (
        db.execute(
            select(Deadline)
            .where(Deadline.user_id == user.id, Deadline.status != "rejected")
            .order_by(Deadline.normalized_at.asc().nullslast())
        )
        .scalars()
        .all()
    )


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: str
    priority: int
    importance: float | None
    estimated_minutes: int | None
    project_id: uuid.UUID | None
    deadline_id: uuid.UUID | None
    provenance: dict | None
    confidence: float


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return db.execute(select(Task).where(Task.user_id == user.id)).scalars().all()


class CommitmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    direction: str
    confidence: str
    status: str
    provenance: dict


@router.get("/commitments", response_model=list[CommitmentOut])
def list_commitments(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return db.execute(select(Commitment).where(Commitment.user_id == user.id)).scalars().all()


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    question: str
    payload: dict
    status: str


@router.get("/review", response_model=list[ReviewOut])
def list_review(
    status_filter: str = "open",
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return (
        db.execute(
            select(ReviewItem)
            .where(ReviewItem.user_id == user.id, ReviewItem.status == status_filter)
            .order_by(ReviewItem.created_at.desc())
        )
        .scalars()
        .all()
    )


class ReviewResolution(BaseModel):
    decision: str  # confirmed | dismissed | corrected
    corrected_date: str | None = None  # ISO date when correcting a deadline


@router.post("/review/{review_id}/resolve")
def resolve_review(
    review_id: uuid.UUID,
    body: ReviewResolution,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    review = db.get(ReviewItem, review_id)
    if review is None or review.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review item not found")
    if review.status != ReviewStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "Review item already resolved")

    resolution: dict = {"decision": body.decision}
    if review.kind == "deadline" and review.payload.get("deadline_id"):
        deadline = db.get(Deadline, uuid.UUID(review.payload["deadline_id"]))
        if deadline is not None:
            if body.decision == "confirmed":
                deadline.status = "confirmed"
                deadline.confidence = max(deadline.confidence, 0.9)
            elif body.decision == "corrected" and body.corrected_date:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                parsed = datetime.fromisoformat(body.corrected_date).replace(
                    tzinfo=ZoneInfo(user.timezone)
                )
                deadline.normalized_at = parsed
                deadline.date_is_exact = True
                deadline.status = "confirmed"
                deadline.confidence = 0.99
                resolution["corrected_date"] = body.corrected_date
            elif body.decision == "dismissed":
                deadline.status = "rejected"
    review.status = ReviewStatus.resolved
    review.resolution = resolution
    db.commit()
    return {"status": review.status, "resolution": resolution}


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent: str
    decision: str
    reason: str
    evidence: dict
    created_at: object


@router.get("/decisions", response_model=list[DecisionOut])
def list_decisions(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return (
        db.execute(
            select(AIDecision)
            .where(AIDecision.user_id == user.id)
            .order_by(AIDecision.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
