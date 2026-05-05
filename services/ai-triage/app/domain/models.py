from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Category(StrEnum):
    BILLING = "Billing"
    TECHNICAL_SUPPORT = "Technical Support"
    ACCOUNT_ACCESS = "Account Access"
    BUG_REPORT = "Bug Report"
    GENERAL_QUERY = "General Query"


class Priority(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    URGENT = "Urgent"


class EscalationRisk(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class AuditAction(StrEnum):
    TRIAGE_COMPLETED = "TRIAGE_COMPLETED"
    HUMAN_REVIEW_RESOLVED = "HUMAN_REVIEW_RESOLVED"
    FEEDBACK_CAPTURED = "FEEDBACK_CAPTURED"


@dataclass(frozen=True)
class TicketCreatedEvent:
    ticket_id: UUID
    title: str
    description: str
    customer_metadata: dict
    channel: str
    created_at: datetime


@dataclass(frozen=True)
class TriageResult:
    id: UUID
    ticket_id: UUID
    category: Category
    priority: Priority
    escalation_risk: EscalationRisk
    assigned_team: str
    confidence: float
    requires_human_review: bool
    model_version: str
    created_at: datetime


@dataclass(frozen=True)
class HumanReview:
    review_id: UUID
    ticket_id: UUID
    triage_result_id: UUID
    status: ReviewStatus
    reason: str
    triage_snapshot: dict
    corrected_category: str | None
    corrected_priority: str | None
    corrected_team: str | None
    corrected_escalation_risk: str | None
    reviewer: str | None
    reviewed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class FeedbackCorrection:
    feedback_id: UUID
    ticket_id: UUID
    triage_result_id: UUID
    review_id: UUID | None
    original_prediction: dict
    corrected_prediction: dict
    reviewer: str
    notes: str | None
    created_at: datetime


@dataclass(frozen=True)
class AuditLog:
    audit_id: UUID
    ticket_id: UUID | None
    actor: str
    action: AuditAction
    details: dict
    created_at: datetime
