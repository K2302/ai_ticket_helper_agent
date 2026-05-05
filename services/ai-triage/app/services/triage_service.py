from app.domain.models import AuditAction, TicketCreatedEvent
from app.infrastructure.repositories import AuditLogRepository, HumanReviewRepository, TriageResultRepository
from app.services.classifier import TicketClassifier
from app.services.confidence import ConfidencePolicy
from app.services.escalation import EscalationScorer
from app.services.openrouter_triage import OpenRouterTriageClient
from app.services.priority import PriorityPredictor
from app.services.routing import RoutingEngine


class TriageService:
    model_version = "rules-v1"

    def __init__(
        self,
        triage_repository: TriageResultRepository,
        human_review_repository: HumanReviewRepository,
        audit_repository: AuditLogRepository,
        classifier: TicketClassifier,
        priority_predictor: PriorityPredictor,
        escalation_scorer: EscalationScorer,
        openrouter_client: OpenRouterTriageClient,
        routing_engine: RoutingEngine,
        confidence_policy: ConfidencePolicy,
    ) -> None:
        self.triage_repository = triage_repository
        self.human_review_repository = human_review_repository
        self.audit_repository = audit_repository
        self.classifier = classifier
        self.priority_predictor = priority_predictor
        self.escalation_scorer = escalation_scorer
        self.openrouter_client = openrouter_client
        self.routing_engine = routing_engine
        self.confidence_policy = confidence_policy

    async def triage(self, ticket: TicketCreatedEvent) -> None:
        llm_prediction = await self.openrouter_client.predict(ticket)
        if llm_prediction is not None:
            category = llm_prediction.category
            priority = llm_prediction.priority
            escalation_risk = llm_prediction.escalation_risk
            confidence = llm_prediction.confidence
            model_version = llm_prediction.model_version
        else:
            category, category_confidence = self.classifier.classify(ticket)
            priority, priority_confidence = self.priority_predictor.predict(ticket)
            escalation_risk, escalation_confidence = self.escalation_scorer.score(ticket)
            confidence = self.confidence_policy.score(
                category_confidence,
                priority_confidence,
                escalation_confidence,
            )
            model_version = self.model_version
        assigned_team = self.routing_engine.route(category, priority, escalation_risk)
        requires_review = self.confidence_policy.requires_review(confidence, priority, escalation_risk)

        result = await self.triage_repository.create(
            ticket_id=ticket.ticket_id,
            category=category,
            priority=priority,
            escalation_risk=escalation_risk,
            assigned_team=assigned_team,
            confidence=confidence,
            requires_human_review=requires_review,
            model_version=model_version,
        )
        await self.audit_repository.create(
            ticket_id=ticket.ticket_id,
            actor="ai-triage-service",
            action=AuditAction.TRIAGE_COMPLETED,
            details={
                "triage_result_id": str(result.id),
                "category": category.value,
                "priority": priority.value,
                "escalation_risk": escalation_risk.value,
                "assigned_team": assigned_team,
                "confidence": confidence,
                "requires_human_review": requires_review,
                "model_version": model_version,
            },
        )

        if requires_review:
            await self.human_review_repository.enqueue(
                triage_result=result,
                reason="LOW_CONFIDENCE" if confidence < self.confidence_policy.low_confidence_threshold else "ESCALATION_REVIEW",
                snapshot={
                    "category": category.value,
                    "priority": priority.value,
                    "escalation_risk": escalation_risk.value,
                    "assigned_team": assigned_team,
                    "confidence": confidence,
                    "model_version": model_version,
                },
            )
