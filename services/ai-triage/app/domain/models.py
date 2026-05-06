from dataclasses import dataclass, field
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
    RISK_DECISION_MADE = "RISK_DECISION_MADE"
    MODEL_PROMOTED = "MODEL_PROMOTED"
    MODEL_RETIRED = "MODEL_RETIRED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"
    REPLAY_STARTED = "REPLAY_STARTED"
    REPLAY_COMPLETED = "REPLAY_COMPLETED"


# --- Phase 3 ---

class RiskDecisionOutcome(StrEnum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class ModelStage(StrEnum):
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    PRIMARY = "PRIMARY"
    RETIRED = "RETIRED"


class OperatingMode(StrEnum):
    """
    Controls how aggressively uncertain / high-risk cases are sent to humans.
    strict_review (fintech v1 default): bias uncertain + high-risk to REVIEW.
    standard: use raw thresholds only.
    """
    STRICT_REVIEW = "strict_review"
    STANDARD = "standard"


# --- Phase 4 ---

class ReplayStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TicketCreatedEvent:
    ticket_id: UUID
    title: str
    description: str
    customer_metadata: dict
    channel: str
    created_at: datetime
    correlation_id: UUID | None = None


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
    correlation_id: UUID | None = None


@dataclass(frozen=True)
class RiskDecision:
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


@dataclass(frozen=True)
class ModelRegistry:
    id: UUID
    name: str
    version: str
    provider: str
    stage: ModelStage
    config: dict
    promoted_at: datetime | None
    retired_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class HumanReview:
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


@dataclass(frozen=True)
class FeedbackCorrection:
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


@dataclass(frozen=True)
class AuditLog:
    audit_id: UUID
    ticket_id: UUID | None
    correlation_id: UUID | None
    actor: str
    action: AuditAction
    details: dict
    created_at: datetime


@dataclass(frozen=True)
class ThresholdConfig:
    id: UUID
    segment_key: str
    block_threshold: float
    review_threshold: float
    approve_threshold: float
    enabled: bool
    updated_at: datetime


@dataclass(frozen=True)
class ModelKillSwitch:
    id: UUID
    provider_key: str
    active: bool
    reason: str | None
    activated_by: str | None
    activated_at: datetime | None
    deactivated_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class ReplayRun:
    id: UUID
    challenger_model_id: UUID
    baseline_model_id: UUID | None
    status: ReplayStatus
    event_window_start: datetime
    event_window_end: datetime
    total_events: int | None
    processed_events: int
    result_summary: dict
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
