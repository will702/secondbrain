import enum


class DocumentKind(enum.StrEnum):
    syllabus = "syllabus"
    lecture_slides = "lecture_slides"
    assignment = "assignment"
    exam = "exam"
    meeting_notes = "meeting_notes"
    schedule = "schedule"
    email_export = "email_export"
    certificate = "certificate"
    competition = "competition"
    notes = "notes"
    reference = "reference"
    other = "other"


class DocumentStatus(enum.StrEnum):
    received = "received"
    parsing = "parsing"
    embedding = "embedding"
    extracting = "extracting"
    review = "review"
    processed = "processed"
    failed = "failed"


class EntityKind(enum.StrEnum):
    person = "person"
    course = "course"
    project = "project"
    organization = "organization"
    topic = "topic"
    concept = "concept"
    location = "location"
    goal = "goal"


class EventKind(enum.StrEnum):
    hard = "hard"
    soft = "soft"
    deadline = "deadline"
    focus = "focus"
    reminder = "reminder"


class TaskStatus(enum.StrEnum):
    proposed = "proposed"
    pending = "pending"
    scheduled = "scheduled"
    in_progress = "in_progress"
    done = "done"
    missed = "missed"
    cancelled = "cancelled"


class CommitmentConfidence(enum.StrEnum):
    confirmed = "confirmed"
    likely = "likely"
    possible = "possible"


class DeadlineStatus(enum.StrEnum):
    tentative = "tentative"
    confirmed = "confirmed"
    rejected = "rejected"


class MemoryLayer(enum.StrEnum):
    working = "working"
    episodic = "episodic"
    semantic = "semantic"
    procedural = "procedural"


class ProposalStatus(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    modified = "modified"
    rejected = "rejected"
    executed = "executed"
    failed = "failed"


class RiskLevel(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class JobStatus(enum.StrEnum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"
    dead = "dead"


class ReviewStatus(enum.StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


class GoalHorizon(enum.StrEnum):
    week = "week"
    month = "month"
    quarter = "quarter"


class GoalStatus(enum.StrEnum):
    active = "active"
    achieved = "achieved"
    dropped = "dropped"
