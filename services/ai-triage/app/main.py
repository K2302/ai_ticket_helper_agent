from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException

from app.core.config import Settings
from app.infrastructure.db import Database
from app.infrastructure.kafka_consumer import TicketKafkaConsumer
from app.infrastructure.repositories import (
    AuditLogRepository,
    FeedbackRepository,
    HumanReviewRepository,
    ModelKillSwitchRepository,
    ModelRegistryRepository,
    ProcessedEventRepository,
    ReplayRunRepository,
    RiskDecisionRepository,
    ThresholdConfigRepository,
    TriageResultRepository,
)
from app.schemas.dto import (
    AuditLogResponse,
    FeedbackCorrectionRequest,
    FeedbackCorrectionResponse,
    HumanReviewDecisionRequest,
    HumanReviewResponse,
    KillSwitchRequest,
    ModelPromoteRequest,
    ModelRegistryResponse,
    RegisterModelRequest,
    ReplayRunRequest,
    ReplayRunResponse,
    RiskDecisionResponse,
    ThresholdUpsertRequest,
    ThresholdConfigResponse,
    TriageResultResponse,
)
from app.services.classifier import TicketClassifier
from app.services.confidence import ConfidencePolicy
from app.services.escalation import EscalationScorer
from app.services.feature_extractor import FeatureExtractor
from app.services.feedback_service import FeedbackService
from app.services.human_review_service import HumanReviewService
from app.services.model_governance_service import ModelGovernanceService
from app.services.model_monitor import ModelMonitorService
from app.services.openrouter_triage import OpenRouterTriageClient
from app.services.policy_engine import PolicyEngine
from app.services.priority import PriorityPredictor
from app.services.replay_service import ReplayService
from app.services.risk_service import RiskScoringService
from app.services.routing import RoutingEngine
from app.services.triage_service import TriageService
from app.domain.models import OperatingMode

settings = Settings()
database = Database(settings.database_url)

triage_repository = TriageResultRepository(database)
review_repository = HumanReviewRepository(database)
feedback_repository = FeedbackRepository(database)
audit_repository = AuditLogRepository(database)
processed_event_repo = ProcessedEventRepository(database)
risk_decision_repo = RiskDecisionRepository(database)
model_registry_repo = ModelRegistryRepository(database)
threshold_config_repo = ThresholdConfigRepository(database)
kill_switch_repo = ModelKillSwitchRepository(database)
replay_run_repo = ReplayRunRepository(database)

feature_extractor = FeatureExtractor()
policy_engine = PolicyEngine()

risk_scoring_service = RiskScoringService(
    risk_decision_repo=risk_decision_repo,
    model_registry_repo=model_registry_repo,
    threshold_config_repo=threshold_config_repo,
    audit_repo=audit_repository,
    feature_extractor=feature_extractor,
    policy_engine=policy_engine,
)
model_governance_service = ModelGovernanceService(
    registry_repo=model_registry_repo,
    kill_switch_repo=kill_switch_repo,
    audit_repo=audit_repository,
)
model_monitor_service = ModelMonitorService(database)
replay_service = ReplayService(
    replay_repo=replay_run_repo,
    risk_decision_repo=risk_decision_repo,
    model_registry_repo=model_registry_repo,
    audit_repo=audit_repository,
    feature_extractor=feature_extractor,
    policy_engine=policy_engine,
)

feedback_service = FeedbackService(feedback_repository, triage_repository, audit_repository)
openrouter_client = OpenRouterTriageClient(settings)
triage_service = TriageService(
    triage_repository=triage_repository,
    human_review_repository=review_repository,
    audit_repository=audit_repository,
    classifier=TicketClassifier(),
    priority_predictor=PriorityPredictor(),
    escalation_scorer=EscalationScorer(),
    openrouter_client=openrouter_client,
    routing_engine=RoutingEngine(),
    confidence_policy=ConfidencePolicy(
        low_confidence_threshold=settings.low_confidence_threshold,
        operating_mode=OperatingMode.STRICT_REVIEW,
    ),
    risk_scoring_service=risk_scoring_service,
    feature_extractor=feature_extractor,
    policy_engine=policy_engine,
)
review_service = HumanReviewService(review_repository, triage_repository, feedback_service, audit_repository)
consumer = TicketKafkaConsumer(settings, triage_service, processed_event_repo)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await consumer.start()
    try:
        yield
    finally:
        await consumer.stop()
        await database.close()


app = FastAPI(title="AI Triage Service", version="2.0.0", lifespan=lifespan)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readiness")
async def readiness() -> dict:
    pool_ok = database.pool is not None
    circuit_ok = not openrouter_client.is_circuit_open()
    return {
        "status": "ready" if pool_ok else "not_ready",
        "db_pool": pool_ok,
        "openrouter_circuit": "closed" if circuit_ok else "open",
    }


# ── Triage ─────────────────────────────────────────────────────────────────────

@app.get("/triage-results/{ticket_id}", response_model=TriageResultResponse)
async def get_triage_result(ticket_id: UUID) -> TriageResultResponse:
    result = await triage_repository.get_by_ticket_id(ticket_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    return TriageResultResponse.from_domain(result)


# ── Risk Decisions ─────────────────────────────────────────────────────────────

@app.get("/risk-decisions/{ticket_id}", response_model=RiskDecisionResponse)
async def get_risk_decision(ticket_id: UUID) -> RiskDecisionResponse:
    decision = await risk_decision_repo.get_by_ticket_id(ticket_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Risk decision not found")
    return RiskDecisionResponse.from_domain(decision)


# ── Human Review ───────────────────────────────────────────────────────────────

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


# ── Feedback ───────────────────────────────────────────────────────────────────

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


# ── Model Registry ─────────────────────────────────────────────────────────────

@app.get("/models", response_model=list[ModelRegistryResponse])
async def list_models() -> list[ModelRegistryResponse]:
    models = await model_governance_service.list_models()
    return [ModelRegistryResponse.from_domain(m) for m in models]


@app.post("/models", response_model=ModelRegistryResponse, status_code=201)
async def register_model(request: RegisterModelRequest) -> ModelRegistryResponse:
    model = await model_governance_service.register(
        name=request.name,
        version=request.version,
        provider=request.provider,
        config=request.config,
    )
    return ModelRegistryResponse.from_domain(model)


@app.post("/models/{model_id}/promote", response_model=ModelRegistryResponse)
async def promote_model(model_id: UUID, request: ModelPromoteRequest) -> ModelRegistryResponse:
    try:
        model = await model_governance_service.promote(model_id, request.target_stage, request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ModelRegistryResponse.from_domain(model)


@app.post("/models/{model_id}/retire", response_model=ModelRegistryResponse)
async def retire_model(model_id: UUID, actor: str = "system") -> ModelRegistryResponse:
    try:
        model = await model_governance_service.retire(model_id, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ModelRegistryResponse.from_domain(model)


# ── Kill Switch ────────────────────────────────────────────────────────────────

@app.post("/kill-switch/activate")
async def activate_kill_switch(request: KillSwitchRequest) -> dict:
    await model_governance_service.activate_kill_switch(
        request.provider_key, request.reason, request.activated_by
    )
    return {"status": "activated", "provider_key": request.provider_key}


@app.post("/kill-switch/deactivate")
async def deactivate_kill_switch(provider_key: str, actor: str = "system") -> dict:
    await model_governance_service.deactivate_kill_switch(provider_key, actor)
    return {"status": "deactivated", "provider_key": provider_key}


# ── Threshold Configuration ────────────────────────────────────────────────────

@app.get("/thresholds", response_model=list[ThresholdConfigResponse])
async def list_thresholds() -> list[ThresholdConfigResponse]:
    configs = await threshold_config_repo.list_all()
    return [ThresholdConfigResponse.from_domain(c) for c in configs]


@app.put("/thresholds", response_model=ThresholdConfigResponse)
async def upsert_threshold(request: ThresholdUpsertRequest) -> ThresholdConfigResponse:
    config = await threshold_config_repo.upsert(
        segment_key=request.segment_key,
        block_threshold=request.block_threshold,
        review_threshold=request.review_threshold,
        approve_threshold=request.approve_threshold,
    )
    return ThresholdConfigResponse.from_domain(config)


# ── Model Monitoring ───────────────────────────────────────────────────────────

@app.get("/models/{model_id}/metrics")
async def get_model_metrics(model_id: UUID) -> dict:
    metrics = await model_monitor_service.get_metrics(model_id)
    return metrics


# ── Replay ─────────────────────────────────────────────────────────────────────

@app.get("/replay-runs", response_model=list[ReplayRunResponse])
async def list_replay_runs() -> list[ReplayRunResponse]:
    runs = await replay_service.list_runs()
    return [ReplayRunResponse.from_domain(r) for r in runs]


@app.post("/replay-runs", response_model=ReplayRunResponse, status_code=201)
async def create_replay_run(request: ReplayRunRequest) -> ReplayRunResponse:
    run = await replay_service.create_run(
        challenger_model_id=request.challenger_model_id,
        baseline_model_id=request.baseline_model_id,
        event_window_start=request.event_window_start,
        event_window_end=request.event_window_end,
        actor=request.actor,
    )
    return ReplayRunResponse.from_domain(run)


@app.post("/replay-runs/{run_id}/execute", response_model=ReplayRunResponse)
async def execute_replay_run(run_id: UUID) -> ReplayRunResponse:
    try:
        run = await replay_service.execute_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ReplayRunResponse.from_domain(run)


@app.get("/replay-runs/{run_id}", response_model=ReplayRunResponse)
async def get_replay_run(run_id: UUID) -> ReplayRunResponse:
    run = await replay_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Replay run not found")
    return ReplayRunResponse.from_domain(run)
