"""Knowledge service: entity resolution (alias + embedding) and graph writes.

Resolution order (cheapest first):
1. exact normalized_name match for the kind
2. alias match
3. embedding cosine ≥ 0.92 → same entity (updates alias)
New entities get an embedding for future resolution. All writes carry
provenance + confidence (DATA_MODEL.md §1, §5).
"""

import re
import unicodedata
from datetime import UTC, datetime

import numpy as np
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.agents.embeddings import get_embedder
from app.models import Entity, EntityMention, EntityRelationship, Person, Project
from app.models.enums import EntityKind

SIMILARITY_THRESHOLD = 0.92

_KINDS = {kind.value for kind in EntityKind}


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def coerce_kind(kind: str) -> EntityKind:
    return EntityKind(kind) if kind in _KINDS else EntityKind.topic


class KnowledgeService:
    def __init__(self, db: OrmSession):
        self.db = db
        self.embedder = get_embedder()

    def resolve(
        self,
        user_id,
        name: str,
        kind: EntityKind,
        confidence: float = 0.5,
        provenance: dict | None = None,
    ) -> Entity:
        """Find-or-create an entity, merging aliases when near-duplicates exist."""
        normalized = normalize_name(name)
        existing = self.db.execute(
            select(Entity).where(
                Entity.user_id == user_id,
                Entity.kind == kind,
                Entity.normalized_name == normalized,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

        alias_match = self.db.execute(
            select(Entity).where(
                Entity.user_id == user_id,
                Entity.kind == kind,
                sa.cast(Entity.aliases, PG_JSONB).contains([normalized]),
            )
        ).scalar_one_or_none()
        if alias_match is not None:
            return alias_match

        # Embedding similarity against same-kind entities (exact scan — small N).
        vector = self.embedder.embed_texts([f"{kind.value}: {name}"])[0]
        candidates = self.db.execute(
            select(Entity).where(Entity.user_id == user_id, Entity.kind == kind)
        ).scalars().all()
        for candidate in candidates:
            if candidate.embedding is None:
                continue
            similarity = float(
                np.dot(candidate.embedding, vector)
                / (np.linalg.norm(candidate.embedding) * np.linalg.norm(vector) + 1e-9)
            )
            if similarity >= SIMILARITY_THRESHOLD:
                if normalized not in candidate.aliases:
                    candidate.aliases = [*candidate.aliases, normalized]
                return candidate

        entity = Entity(
            user_id=user_id,
            kind=kind,
            name=name.strip(),
            normalized_name=normalized,
            confidence=confidence,
            embedding=vector,
        )
        self.db.add(entity)
        self.db.flush()
        return entity

    def link_relationship(
        self,
        user_id,
        subject: Entity,
        predicate: str,
        object: Entity,
        confidence: float,
        provenance: dict,
    ) -> None:
        if subject.id == object.id:
            return
        existing = self.db.execute(
            select(EntityRelationship).where(
                EntityRelationship.subject_entity_id == subject.id,
                EntityRelationship.predicate == predicate,
                EntityRelationship.object_entity_id == object.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if confidence > existing.confidence:  # keep the strongest evidence
                existing.confidence = confidence
            return
        self.db.add(
            EntityRelationship(
                user_id=user_id,
                subject_entity_id=subject.id,
                predicate=predicate,
                object_entity_id=object.id,
                confidence=confidence,
                provenance=provenance,
            )
        )

    def add_mention(
        self, user_id, chunk, entity: Entity, surface_form: str, confidence: float
    ) -> None:
        self.db.add(
            EntityMention(
                user_id=user_id,
                chunk_id=chunk.id,
                entity_id=entity.id,
                surface_form=surface_form[:500],
                confidence=confidence,
            )
        )

    def ensure_project(self, user_id, name: str, kind: str = "course", provenance: dict | None = None) -> Project:
        entity = self.resolve(user_id, name, EntityKind.course if kind == "course" else EntityKind.project, provenance=provenance)
        project = self.db.execute(
            select(Project).where(Project.entity_id == entity.id)
        ).scalar_one_or_none()
        if project is None:
            project = Project(user_id=user_id, entity_id=entity.id, name=entity.name, kind=kind)
            self.db.add(project)
            self.db.flush()
        return project

    def ensure_person(self, user_id, name: str, provenance: dict | None = None) -> Person:
        entity = self.resolve(user_id, name, EntityKind.person, provenance=provenance)
        person = self.db.execute(
            select(Person).where(Person.entity_id == entity.id)
        ).scalar_one_or_none()
        if person is None:
            person = Person(user_id=user_id, entity_id=entity.id, name=entity.name)
            self.db.add(person)
            self.db.flush()
        return person


def provenance_for(document, chunk=None, extractor: str = "knowledge") -> dict:
    return {
        "document_id": str(document.id),
        "chunk_id": str(chunk.id) if chunk else None,
        "page": chunk.page if chunk else None,
        "extractor": extractor,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
