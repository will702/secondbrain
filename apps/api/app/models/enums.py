import enum


class DocumentKind(str, enum.Enum):
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


class DocumentStatus(str, enum.Enum):
    received = "received"
    parsing = "parsing"
    embedding = "embedding"
    extracting = "extracting"
    review = "review"
    processed = "processed"
    failed = "failed"


class EntityKind(str, enum.Enum):
    person = "person"
    course = "course"
    project = "project"
    organization = "organization"
    topic = "topic"
    concept = "concept"
    location = "location"
    goal = "goal"


class EventKind(str, enum.Enum):
    hard = "hard"
    soft = "soft"
    deadline = "deadline"
    focus = "focus"
    reminder = "reminder"


class TaskStatus(str, enum.Enum):
    proposed = "proposed"
    pending = "pending"
    scheduled = "scheduled"
    in_progress = "in_progress"
    done = "done"
    missed = "missed"
    cancelled = "cancelled"


class CommitmentConfidence(str, enum.Enum):
    confirmed = "confirmed"
    likely = "likely"
    possible = "possible"


class DeadlineStatus(str, enum.Enum):
    tentative = "tentative"
    confirmed = "confirmed"
    rejected = "rejected"


class MemoryLayer(str, enum.Enum):
    working = "working"
    episodic = "episodic"
    semantic = "semantic"
    procedural = "procedural"


class ProposalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    modified = "modified"
    rejected = "rejected"
    executed = "executed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class JobStatus(str, enum.Enum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"
    dead = "dead"


class ReviewStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"
