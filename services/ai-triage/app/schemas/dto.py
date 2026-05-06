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
    ModelKillSwitch,
    ModelRegistry,
    ModelStage,
    Priority,
    ReplayRun,
    ReviewStatus,
    RiskDecision,
    RiskDecisionOutcome,
    ThresholdConfig,
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
    correlation_id: UUID | None
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
            correlation_id=result.correlation_id,
            created_at=result.created_at,
        )


class RiskDecisionResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    triage_result_id: UUID | None
    correlation_id: UUID
    model_registry_id: UUID | None
    decision: RiskDecisionOutcome
    reason_code: str
    score: float
    policy_override: bool
    policy_rule: str | None
    feature_snapshot: dict
    feature_snapshot_hash: str | None
    explainability: dict
    model_version: str
    rule_version: str
    prompt_version: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, d: RiskDecision) -> "RiskDecisionResponse":
        return cls(**d.__dict__)


class HumanReviewResponse(BaseModel):
    review_id: UUID
    ticket_id: UUID
    triage_result_id: UUID
    risk_decision_id: UUID | None
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
    risk_decision_id: UUID | None
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
    correlation_id: UUID | None
    actor: str
    action: AuditAction
    details: dict
    created_at: datetime

    @classmethod
    def from_domain(cls, log: AuditLog) -> "AuditLogResponse":
        return cls(**log.__dict__)


# ── Model Registry ──────────────────────────────────────────────────────────────

class RegisterModelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=120)
    config: dict = Field(default_factory=dict)


class ModelPromoteRequest(BaseModel):
    target_stage: ModelStage
    actor: str = Field(min_length=1, max_length=200)


class ModelRegistryResponse(BaseModel):
    id: UUID
    name: str
    version: str
    provider: str
    stage: ModelStage
    config: dict
    promoted_at: datetime | None
    retired_at: datetime | None
    created_at: datetime

    @classmethod
    def from_domain(cls, m: ModelRegistry) -> "ModelRegistryResponse":
        return cls(**m.__dict__)


# ── Kill Switch ─────────────────────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    activated_by: str = Field(min_length=1, max_length=200)


# ── Threshold Config ────────────────────────────────────────────────────────────

class ThresholdUpsertRequest(BaseModel):
    segment_key: str = Field(min_length=1, max_length=200)
    block_threshold: float = Field(ge=0.0, le=1.0)
    review_threshold: float = Field(ge=0.0, le=1.0)
    approve_threshold: float = Field(ge=0.0, le=1.0)


class ThresholdConfigResponse(BaseModel):
    id: UUID
    segment_key: str
    block_threshold: float
    review_threshold: float
    approve_threshold: float
    enabled: bool
    updated_at: datetime

    @classmethod
    def from_domain(cls, c: ThresholdConfig) -> "ThresholdConfigResponse":
        return cls(**c.__dict__)


# ── Replay ──────────────────────────────────────────────────────────────────────

class ReplayRunRequest(BaseModel):
    challenger_model_id: UUID
    baseline_model_id: UUID | None = None
    event_window_start: datetime
    event_window_end: datetime
    actor: str = Field(min_length=1, max_length=200)


class ReplayRunResponse(BaseModel):
    id: UUID
    challenger_model_id: UUID
    baseline_model_id: UUID | None
    status: str
    event_window_start: datetime
    event_window_end: datetime
    total_events: int | None
    processed_events: int
    result_summary: dict
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @classmethod
    def from_domain(cls, r: ReplayRun) -> "ReplayRunResponse":
        return cls(**r.__dict__)
