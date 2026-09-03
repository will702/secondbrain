"""Document-to-fact lineage and source-safe retraction."""

import uuid
from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    ActionProposal,
    AuditLog,
    Commitment,
    Deadline,
    Document,
    DocumentDerivation,
    Entity,
    EntityMention,
    EntityRelationship,
    Event,
    Person,
    Project,
    ReviewItem,
    Task,
    TaskDependency,
    User,
)
from app.models.enums import ProposalStatus
from app.services.storage import Storage

MODEL_BY_TYPE = {
    "commitment": Commitment,
    "deadline": Deadline,
    "entity": Entity,
    "relationship": EntityRelationship,
    "project": Project,
    "review": ReviewItem,
    "task": Task,
}


def record_derivation(
    db: OrmSession,
    document_id: uuid.UUID,
    object_type: str,
    object_id: uuid.UUID,
    provenance: dict,
) -> None:
    exists = db.execute(
        sa.select(DocumentDerivation.id).where(
            DocumentDerivation.document_id == document_id,
            DocumentDerivation.object_type == object_type,
            DocumentDerivation.object_id == object_id,
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            DocumentDerivation(
                document_id=document_id,
                object_type=object_type,
                object_id=object_id,
                provenance=provenance,
            )
        )


def _has_other_source(db: OrmSession, edge: DocumentDerivation) -> bool:
    return (
        db.execute(
            sa.select(DocumentDerivation.id)
            .where(
                DocumentDerivation.document_id != edge.document_id,
                DocumentDerivation.object_type == edge.object_type,
                DocumentDerivation.object_id == edge.object_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _delete_task(db: OrmSession, task: Task) -> None:
    db.query(Event).filter(Event.task_id == task.id).delete(synchronize_session=False)
    db.query(TaskDependency).filter(
        sa.or_(TaskDependency.task_id == task.id, TaskDependency.depends_on_task_id == task.id)
    ).delete(synchronize_session=False)
    db.query(Deadline).filter(Deadline.task_id == task.id).update(
        {Deadline.task_id: None}, synchronize_session=False
    )
    db.delete(task)


def _delete_deadline(db: OrmSession, deadline: Deadline) -> None:
    db.query(Task).filter(Task.deadline_id == deadline.id).update(
        {Task.deadline_id: None}, synchronize_session=False
    )
    db.query(Commitment).filter(Commitment.deadline_id == deadline.id).update(
        {Commitment.deadline_id: None}, synchronize_session=False
    )
    db.delete(deadline)


def _project_is_orphan(db: OrmSession, project: Project, document_id: uuid.UUID) -> bool:
    references = (
        db.query(Document)
        .filter(Document.id != document_id, Document.project_id == project.id)
        .count()
        + db.query(Task).filter(Task.project_id == project.id).count()
        + db.query(Deadline).filter(Deadline.project_id == project.id).count()
        + db.query(Commitment).filter(Commitment.project_id == project.id).count()
        + db.query(Event).filter(Event.project_id == project.id).count()
    )
    return references == 0


def _entity_is_orphan(db: OrmSession, entity: Entity) -> bool:
    references = (
        db.query(EntityMention).filter(EntityMention.entity_id == entity.id).count()
        + db.query(EntityRelationship)
        .filter(
            sa.or_(
                EntityRelationship.subject_entity_id == entity.id,
                EntityRelationship.object_entity_id == entity.id,
            )
        )
        .count()
        + db.query(Project).filter(Project.entity_id == entity.id).count()
        + db.query(Person).filter(Person.entity_id == entity.id).count()
        + db.query(Task).filter(Task.related_entity_id == entity.id).count()
        + db.query(Commitment).filter(Commitment.person_entity_id == entity.id).count()
    )
    return references == 0


def retract_document(db: OrmSession, user: User, document: Document) -> None:
    """Retract source-only facts, retaining shared objects and immutable audit history."""
    db.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:document_id))"),
        {"document_id": str(document.id)},
    )
    db.refresh(document)
    edges = (
        db.execute(
            sa.select(DocumentDerivation).where(DocumentDerivation.document_id == document.id)
        )
        .scalars()
        .all()
    )
    exclusive: dict[str, list[uuid.UUID]] = defaultdict(list)
    for edge in edges:
        if not _has_other_source(db, edge):
            exclusive[edge.object_type].append(edge.object_id)

    task_ids = exclusive["task"]
    task_id_strings = {str(task_id) for task_id in task_ids}
    for proposal in db.execute(
        sa.select(ActionProposal).where(
            ActionProposal.user_id == user.id,
            ActionProposal.status == ProposalStatus.pending,
            ActionProposal.proposed_by == "planning",
        )
    ).scalars():
        evidence_task = str((proposal.evidence or {}).get("task_id") or "")
        if evidence_task in task_id_strings:
            db.delete(proposal)

    for object_type in ("review", "relationship", "commitment"):
        model = MODEL_BY_TYPE[object_type]
        for object_id in exclusive[object_type]:
            row = db.get(model, object_id)
            if row is not None:
                db.delete(row)

    for task_id in task_ids:
        task = db.get(Task, task_id)
        if task is not None:
            _delete_task(db, task)
    for deadline_id in exclusive["deadline"]:
        deadline = db.get(Deadline, deadline_id)
        if deadline is not None:
            _delete_deadline(db, deadline)

    candidate_projects = [db.get(Project, object_id) for object_id in exclusive["project"]]
    candidate_entities = [db.get(Entity, object_id) for object_id in exclusive["entity"]]
    db.delete(document)
    db.flush()

    for project in candidate_projects:
        if project is not None and _project_is_orphan(db, project, document.id):
            db.delete(project)
    db.flush()
    for entity in candidate_entities:
        if entity is not None and _entity_is_orphan(db, entity):
            db.delete(entity)

    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="document.delete",
            object_type="document",
            object_id=str(document.id),
            detail={"filename": document.original_filename},
        )
    )
    digest = document.sha256
    db.commit()
    Storage().delete(user.id, digest)
