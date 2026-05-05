from uuid import UUID

from app.domain.models import AuditAction, HumanReview
from app.infrastructure.repositories import AuditLogRepository, HumanReviewRepository, TriageResultRepository
from app.schemas.dto import FeedbackCorrectionRequest, HumanReviewDecisionRequest
from app.services.feedback_service import FeedbackService


class HumanReviewService:
    def __init__(
        self,
        review_repository: HumanReviewRepository,
        triage_repository: TriageResultRepository,
        feedback_service: FeedbackService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self.review_repository = review_repository
        self.triage_repository = triage_repository
        self.feedback_service = feedback_service
        self.audit_repository = audit_repository

    async def list_pending(self) -> list[HumanReview]:
        return await self.review_repository.list_pending()

    async def decide(self, review_id: UUID, request: HumanReviewDecisionRequest) -> HumanReview | None:
        pending_reviews = await self.review_repository.list_pending()
        pending_review = next((review for review in pending_reviews if review.review_id == review_id), None)
        if pending_review is None:
            return None
        triage_result = await self.triage_repository.get_by_id(pending_review.triage_result_id)
        if triage_result is None:
            return None

        review = await self.review_repository.resolve(
            review_id=review_id,
            reviewer=request.reviewer,
            corrected_category=request.corrected_category,
            corrected_priority=request.corrected_priority,
            corrected_team=request.corrected_team,
            corrected_escalation_risk=request.corrected_escalation_risk,
        )
        if review is None:
            return None

        feedback_request = FeedbackCorrectionRequest(
            reviewer=request.reviewer,
            corrected_category=request.corrected_category,
            corrected_priority=request.corrected_priority,
            corrected_team=request.corrected_team,
            corrected_escalation_risk=request.corrected_escalation_risk,
            notes=request.notes,
        )
        await self.feedback_service.create_for_result(triage_result, feedback_request, review.review_id)
        await self.triage_repository.apply_override(
            result_id=review.triage_result_id,
            category=request.corrected_category,
            priority=request.corrected_priority,
            escalation_risk=request.corrected_escalation_risk,
            assigned_team=request.corrected_team,
        )
        await self.audit_repository.create(
            ticket_id=review.ticket_id,
            actor=request.reviewer,
            action=AuditAction.HUMAN_REVIEW_RESOLVED,
            details={
                "review_id": str(review.review_id),
                "triage_result_id": str(review.triage_result_id),
            },
        )
        return review
