from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models import (
    AuditAction,
    AuditLog,
    Category,
    EscalationRisk,
    FeedbackCorrection,
    HumanReview,
    Priority,
    ReviewStatus,
    TriageResult,
)


class TriageResultResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    category: str
    priority: Priority
    escalation_risk: EscalationRisk
    assigned_team: str
    confidence: float
    requires_human_review: bool
    model_version: str
    created_at: datetime

    @classmethod
    def from_domain(cls, result: TriageResult) -> "TriageResultResponse":
        return cls(
            id=result.id,
            ticket_id=result.ticket_id,
            category=result.category,
            priority=result.priority,
            escalation_risk=result.escalation_risk,
            assigned_team=result.assigned_team,
            confidence=result.confidence,
            requires_human_review=result.requires_human_review,
            model_version=result.model_version,
            created_at=result.created_at,
        )


class HumanReviewResponse(BaseModel):
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

    @classmethod
    def from_domain(cls, review: HumanReview) -> "HumanReviewResponse":
        return cls(**review.__dict__)


class HumanReviewDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    corrected_category: Category
    corrected_priority: Priority
    corrected_team: str = Field(min_length=1, max_length=80)
    corrected_escalation_risk: EscalationRisk
    notes: str | None = Field(default=None, max_length=1000)


class FeedbackCorrectionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    corrected_category: Category
    corrected_priority: Priority
    corrected_team: str = Field(min_length=1, max_length=80)
    corrected_escalation_risk: EscalationRisk
    notes: str | None = Field(default=None, max_length=1000)


class FeedbackCorrectionResponse(BaseModel):
    feedback_id: UUID
    ticket_id: UUID
    triage_result_id: UUID
    review_id: UUID | None
    original_prediction: dict
    corrected_prediction: dict
    reviewer: str
    notes: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, feedback: FeedbackCorrection) -> "FeedbackCorrectionResponse":
        return cls(**feedback.__dict__)


class AuditLogResponse(BaseModel):
    audit_id: UUID
    ticket_id: UUID | None
    actor: str
    action: AuditAction
    details: dict
    created_at: datetime

    @classmethod
    def from_domain(cls, log: AuditLog) -> "AuditLogResponse":
        return cls(**log.__dict__)
