from uuid import UUID

from app.domain.models import AuditAction, FeedbackCorrection, TriageResult
from app.infrastructure.repositories import AuditLogRepository, FeedbackRepository, TriageResultRepository
from app.schemas.dto import FeedbackCorrectionRequest


class FeedbackService:
    def __init__(
        self,
        feedback_repository: FeedbackRepository,
        triage_repository: TriageResultRepository,
        audit_repository: AuditLogRepository,
    ) -> None:
        self.feedback_repository = feedback_repository
        self.triage_repository = triage_repository
        self.audit_repository = audit_repository

    async def create_for_ticket(
        self,
        ticket_id: UUID,
        request: FeedbackCorrectionRequest,
        review_id: UUID | None = None,
    ) -> FeedbackCorrection | None:
        triage_result = await self.triage_repository.get_by_ticket_id(ticket_id)
        if triage_result is None:
            return None
        return await self.create_for_result(triage_result, request, review_id)

    async def create_for_result(
        self,
        triage_result: TriageResult,
        request: FeedbackCorrectionRequest,
        review_id: UUID | None = None,
    ) -> FeedbackCorrection:
        original = {
            "category": triage_result.category.value,
            "priority": triage_result.priority.value,
            "escalation_risk": triage_result.escalation_risk.value,
            "assigned_team": triage_result.assigned_team,
            "confidence": triage_result.confidence,
            "model_version": triage_result.model_version,
        }
        corrected = {
            "category": request.corrected_category.value,
            "priority": request.corrected_priority.value,
            "escalation_risk": request.corrected_escalation_risk.value,
            "assigned_team": request.corrected_team,
        }
        feedback = await self.feedback_repository.create(
            ticket_id=triage_result.ticket_id,
            triage_result_id=triage_result.id,
            review_id=review_id,
            original_prediction=original,
            corrected_prediction=corrected,
            reviewer=request.reviewer,
            notes=request.notes,
        )
        await self.audit_repository.create(
            ticket_id=triage_result.ticket_id,
            actor=request.reviewer,
            action=AuditAction.FEEDBACK_CAPTURED,
            details={
                "feedback_id": str(feedback.feedback_id),
                "triage_result_id": str(triage_result.id),
                "review_id": str(review_id) if review_id else None,
                "corrected_prediction": corrected,
            },
        )
        return feedback

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[FeedbackCorrection]:
        return await self.feedback_repository.list_by_ticket_id(ticket_id)
