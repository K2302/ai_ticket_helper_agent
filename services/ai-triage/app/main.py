from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException

from app.core.config import Settings
from app.infrastructure.db import Database
from app.infrastructure.kafka_consumer import TicketKafkaConsumer
from app.infrastructure.repositories import (
    AuditLogRepository,
    FeedbackRepository,
    HumanReviewRepository,
    TriageResultRepository,
)
from app.schemas.dto import (
    AuditLogResponse,
    FeedbackCorrectionRequest,
    FeedbackCorrectionResponse,
    HumanReviewDecisionRequest,
    HumanReviewResponse,
    TriageResultResponse,
)
from app.services.classifier import TicketClassifier
from app.services.confidence import ConfidencePolicy
from app.services.escalation import EscalationScorer
from app.services.feedback_service import FeedbackService
from app.services.human_review_service import HumanReviewService
from app.services.openrouter_triage import OpenRouterTriageClient
from app.services.priority import PriorityPredictor
from app.services.routing import RoutingEngine
from app.services.triage_service import TriageService

settings = Settings()
database = Database(settings.database_url)

triage_repository = TriageResultRepository(database)
review_repository = HumanReviewRepository(database)
feedback_repository = FeedbackRepository(database)
audit_repository = AuditLogRepository(database)
feedback_service = FeedbackService(feedback_repository, triage_repository, audit_repository)
triage_service = TriageService(
    triage_repository=triage_repository,
    human_review_repository=review_repository,
    audit_repository=audit_repository,
    classifier=TicketClassifier(),
    priority_predictor=PriorityPredictor(),
    escalation_scorer=EscalationScorer(),
    openrouter_client=OpenRouterTriageClient(settings),
    routing_engine=RoutingEngine(),
    confidence_policy=ConfidencePolicy(settings.low_confidence_threshold),
)
review_service = HumanReviewService(review_repository, triage_repository, feedback_service, audit_repository)
consumer = TicketKafkaConsumer(settings, triage_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await consumer.start()
    try:
        yield
    finally:
        await consumer.stop()
        await database.close()


app = FastAPI(title="AI Triage Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/triage-results/{ticket_id}", response_model=TriageResultResponse)
async def get_triage_result(ticket_id: UUID) -> TriageResultResponse:
    result = await triage_repository.get_by_ticket_id(ticket_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    return TriageResultResponse.from_domain(result)


@app.get("/reviews/pending", response_model=list[HumanReviewResponse])
async def list_pending_reviews() -> list[HumanReviewResponse]:
    reviews = await review_service.list_pending()
    return [HumanReviewResponse.from_domain(review) for review in reviews]


@app.post("/reviews/{review_id}/decision", response_model=HumanReviewResponse)
async def decide_review(review_id: UUID, request: HumanReviewDecisionRequest) -> HumanReviewResponse:
    review = await review_service.decide(review_id, request)
    if review is None:
        raise HTTPException(status_code=404, detail="Pending review not found")
    return HumanReviewResponse.from_domain(review)


@app.post("/tickets/{ticket_id}/feedback", response_model=FeedbackCorrectionResponse)
async def create_feedback(ticket_id: UUID, request: FeedbackCorrectionRequest) -> FeedbackCorrectionResponse:
    feedback = await feedback_service.create_for_ticket(ticket_id, request)
    if feedback is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    return FeedbackCorrectionResponse.from_domain(feedback)


@app.get("/tickets/{ticket_id}/feedback", response_model=list[FeedbackCorrectionResponse])
async def list_feedback(ticket_id: UUID) -> list[FeedbackCorrectionResponse]:
    feedback = await feedback_service.list_by_ticket_id(ticket_id)
    return [FeedbackCorrectionResponse.from_domain(item) for item in feedback]


@app.get("/tickets/{ticket_id}/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(ticket_id: UUID) -> list[AuditLogResponse]:
    logs = await audit_repository.list_by_ticket_id(ticket_id)
    return [AuditLogResponse.from_domain(log) for log in logs]
