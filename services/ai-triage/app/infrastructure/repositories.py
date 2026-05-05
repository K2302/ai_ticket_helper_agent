import json
from uuid import UUID

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
from app.infrastructure.db import Database


class TriageResultRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        assigned_team: str,
        confidence: float,
        requires_human_review: bool,
        model_version: str,
    ) -> TriageResult:
        row = await self.database.require_pool().fetchrow(
            """
            insert into triage_results (
                ticket_id, category, priority, escalation_risk, assigned_team,
                confidence, requires_human_review, model_version
            )
            values ($1, $2, $3, $4, $5, $6, $7, $8)
            on conflict (ticket_id) do update set
                category = excluded.category,
                priority = excluded.priority,
                escalation_risk = excluded.escalation_risk,
                assigned_team = excluded.assigned_team,
                confidence = excluded.confidence,
                requires_human_review = excluded.requires_human_review,
                model_version = excluded.model_version
            returning *
            """,
            ticket_id,
            category.value,
            priority.value,
            escalation_risk.value,
            assigned_team,
            confidence,
            requires_human_review,
            model_version,
        )
        return self._to_domain(row)

    async def get_by_ticket_id(self, ticket_id: UUID) -> TriageResult | None:
        row = await self.database.require_pool().fetchrow(
            "select * from triage_results where ticket_id = $1",
            ticket_id,
        )
        return self._to_domain(row) if row else None

    async def get_by_id(self, result_id: UUID) -> TriageResult | None:
        row = await self.database.require_pool().fetchrow(
            "select * from triage_results where id = $1",
            result_id,
        )
        return self._to_domain(row) if row else None

    async def apply_override(
        self,
        result_id: UUID,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        assigned_team: str,
    ) -> None:
        await self.database.require_pool().execute(
            """
            update triage_results
            set category = $2,
                priority = $3,
                escalation_risk = $4,
                assigned_team = $5,
                requires_human_review = false
            where id = $1
            """,
            result_id,
            category.value,
            priority.value,
            escalation_risk.value,
            assigned_team,
        )

    def _to_domain(self, row) -> TriageResult:
        return TriageResult(
            id=row["id"],
            ticket_id=row["ticket_id"],
            category=Category(row["category"]),
            priority=Priority(row["priority"]),
            escalation_risk=EscalationRisk(row["escalation_risk"]),
            assigned_team=row["assigned_team"],
            confidence=float(row["confidence"]),
            requires_human_review=row["requires_human_review"],
            model_version=row["model_version"],
            created_at=row["created_at"],
        )


class HumanReviewRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def enqueue(self, triage_result: TriageResult, reason: str, snapshot: dict) -> HumanReview:
        row = await self.database.require_pool().fetchrow(
            """
            insert into human_review_queue (
                ticket_id, triage_result_id, reason, triage_snapshot
            )
            values ($1, $2, $3, $4::jsonb)
            on conflict (ticket_id) where status = 'PENDING' do update set
                triage_result_id = excluded.triage_result_id,
                reason = excluded.reason,
                triage_snapshot = excluded.triage_snapshot
            returning *
            """,
            triage_result.ticket_id,
            triage_result.id,
            reason,
            json.dumps(snapshot),
        )
        return self._to_domain(row)

    async def list_pending(self) -> list[HumanReview]:
        rows = await self.database.require_pool().fetch(
            """
            select * from human_review_queue
            where status = 'PENDING'
            order by created_at asc
            """
        )
        return [self._to_domain(row) for row in rows]

    async def resolve(
        self,
        review_id: UUID,
        reviewer: str,
        corrected_category: Category,
        corrected_priority: Priority,
        corrected_team: str,
        corrected_escalation_risk: EscalationRisk,
    ) -> HumanReview | None:
        row = await self.database.require_pool().fetchrow(
            """
            update human_review_queue
            set status = 'RESOLVED',
                reviewer = $2,
                corrected_category = $3,
                corrected_priority = $4,
                corrected_team = $5,
                corrected_escalation_risk = $6,
                reviewed_at = now()
            where review_id = $1 and status = 'PENDING'
            returning *
            """,
            review_id,
            reviewer,
            corrected_category.value,
            corrected_priority.value,
            corrected_team,
            corrected_escalation_risk.value,
        )
        return self._to_domain(row) if row else None

    def _to_domain(self, row) -> HumanReview:
        return HumanReview(
            review_id=row["review_id"],
            ticket_id=row["ticket_id"],
            triage_result_id=row["triage_result_id"],
            status=ReviewStatus(row["status"]),
            reason=row["reason"],
            triage_snapshot=self._json_dict(row["triage_snapshot"]),
            corrected_category=row["corrected_category"],
            corrected_priority=row["corrected_priority"],
            corrected_team=row["corrected_team"],
            corrected_escalation_risk=row["corrected_escalation_risk"],
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class FeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID,
        triage_result_id: UUID,
        review_id: UUID | None,
        original_prediction: dict,
        corrected_prediction: dict,
        reviewer: str,
        notes: str | None,
    ) -> FeedbackCorrection:
        row = await self.database.require_pool().fetchrow(
            """
            insert into feedback_corrections (
                ticket_id, triage_result_id, review_id, original_prediction,
                corrected_prediction, reviewer, notes
            )
            values ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
            returning *
            """,
            ticket_id,
            triage_result_id,
            review_id,
            json.dumps(original_prediction),
            json.dumps(corrected_prediction),
            reviewer,
            notes,
        )
        return self._to_domain(row)

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[FeedbackCorrection]:
        rows = await self.database.require_pool().fetch(
            """
            select * from feedback_corrections
            where ticket_id = $1
            order by created_at desc
            """,
            ticket_id,
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> FeedbackCorrection:
        return FeedbackCorrection(
            feedback_id=row["feedback_id"],
            ticket_id=row["ticket_id"],
            triage_result_id=row["triage_result_id"],
            review_id=row["review_id"],
            original_prediction=self._json_dict(row["original_prediction"]),
            corrected_prediction=self._json_dict(row["corrected_prediction"]),
            reviewer=row["reviewer"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class AuditLogRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID | None,
        actor: str,
        action: AuditAction,
        details: dict,
    ) -> AuditLog:
        row = await self.database.require_pool().fetchrow(
            """
            insert into audit_logs (ticket_id, actor, action, details)
            values ($1, $2, $3, $4::jsonb)
            returning *
            """,
            ticket_id,
            actor,
            action.value,
            json.dumps(details),
        )
        return self._to_domain(row)

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[AuditLog]:
        rows = await self.database.require_pool().fetch(
            """
            select * from audit_logs
            where ticket_id = $1
            order by created_at desc
            """,
            ticket_id,
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> AuditLog:
        return AuditLog(
            audit_id=row["audit_id"],
            ticket_id=row["ticket_id"],
            actor=row["actor"],
            action=AuditAction(row["action"]),
            details=self._json_dict(row["details"]),
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)
