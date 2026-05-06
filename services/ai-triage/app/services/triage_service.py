import logging

from app.domain.models import AuditAction, TicketCreatedEvent
from app.infrastructure.repositories import AuditLogRepository, HumanReviewRepository, TriageResultRepository
from app.services.classifier import TicketClassifier, _path_confidence
from app.services.confidence import ConfidencePolicy
from app.services.escalation import EscalationScorer
from app.services.feature_extractor import FeatureExtractor
from app.services.openrouter_triage import OpenRouterTriageClient
from app.services.policy_engine import PolicyEngine
from app.services.priority import PriorityPredictor
from app.services.risk_service import RiskScoringService
from app.services.routing import RoutingEngine

logger = logging.getLogger(__name__)


class TriageService:
    """
    Orchestrates the human-first triage pipeline:

    1. Extract features (includes Tier-0 fintech risk signals).
    2. Tier-0 hard rules (sanctions, impossible-travel, velocity, auth, device).
       If a Tier-0 rule fires → BLOCK/REVIEW immediately, skip LLM entirely.
    3. LLM feature extraction (assistive only — never writes final decision).
       If LLM unavailable / schema-invalid → fall back to deterministic rules.
    4. Tier-1 contextual policy rules.
    5. Risk scoring → final APPROVE/REVIEW/BLOCK decision with full evidence.
    6. Human review queue entry if required.
    """

    _RULES_MODEL_VERSION = "rules-v1"

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
        risk_scoring_service: RiskScoringService,
        feature_extractor: FeatureExtractor,
        policy_engine: PolicyEngine,
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
        self.risk_scoring_service = risk_scoring_service
        self.feature_extractor = feature_extractor
        self.policy_engine = policy_engine

    async def triage(self, ticket: TicketCreatedEvent) -> None:
        # ── Step 1: extract features (Tier-0 signals from metadata) ──────────
        features = self.feature_extractor.extract(ticket)

        # ── Step 2: Tier-0 hard rules — executed BEFORE LLM ──────────────────
        tier0_result = self.policy_engine.evaluate_tier0(features)
        tier0_fired = tier0_result is not None
        if tier0_fired:
            _t0_decision, _t0_reason, _, _t0_rule = tier0_result
            logger.info(
                "Tier-0 rule %s fired for ticket %s — skipping LLM",
                _t0_rule, ticket.ticket_id,
            )

        # ── Step 3: LLM feature extraction (assistive, skipped on Tier-0 hit) ─
        llm_features = None
        if not tier0_fired:
            llm_features = await self.openrouter_client.extract_features(ticket)

        # ── Step 4: Resolve category / priority / escalation_risk ─────────────
        decision_path: list[int] = []
        target_team_hint: str | None = None

        if llm_features is not None:
            category = llm_features.category
            priority = llm_features.priority
            escalation_risk = llm_features.escalation_risk
            confidence = llm_features.confidence
            model_version = llm_features.model_version
            decision_path = llm_features.decision_path or []
        else:
            # Rules-only path: tree-based deterministic classifiers
            tree_decision = self.classifier.classify_with_tree(ticket)
            category = tree_decision.category
            target_team_hint = tree_decision.target_team
            decision_path = tree_decision.decision_path

            priority, priority_confidence = self.priority_predictor.predict(ticket)
            escalation_risk, escalation_confidence = self.escalation_scorer.score(ticket, features=features)
            category_confidence = _path_confidence(decision_path)
            confidence = self.confidence_policy.score(
                category_confidence,
                priority_confidence,
                escalation_confidence,
            )
            model_version = self._RULES_MODEL_VERSION

        # ── Step 5: routing ───────────────────────────────────────────────────
        assigned_team = self.routing_engine.route(
            category, priority, escalation_risk,
            target_team_hint=target_team_hint,
        )

        # ── Step 6: segment-aware requires_review (Phase 3 matrix) ───────────
        requires_review = self.confidence_policy.requires_review(
            confidence, priority, escalation_risk, features=features
        )

        # ── Step 7: persist triage result ────────────────────────────────────
        result = await self.triage_repository.create(
            ticket_id=ticket.ticket_id,
            category=category,
            priority=priority,
            escalation_risk=escalation_risk,
            assigned_team=assigned_team,
            confidence=confidence,
            requires_human_review=requires_review,
            model_version=model_version,
            correlation_id=ticket.correlation_id,
        )
        await self.audit_repository.create(
            ticket_id=ticket.ticket_id,
            actor="ai-triage-service",
            action=AuditAction.TRIAGE_COMPLETED,
            correlation_id=ticket.correlation_id,
            details={
                "triage_result_id": str(result.id),
                "category": category.value,
                "priority": priority.value,
                "escalation_risk": escalation_risk.value,
                "assigned_team": assigned_team,
                "confidence": confidence,
                "requires_human_review": requires_review,
                "model_version": model_version,
                "tier0_fired": tier0_fired,
                "llm_used": llm_features is not None,
                "decision_path": decision_path,
            },
        )

        # ── Step 8: risk decision (includes policy engine, full evidence) ─────
        risk_decision = await self.risk_scoring_service.decide(ticket, result, features=features)

        # ── Step 9: enqueue human review if required ──────────────────────────
        if requires_review:
            reason = (
                tier0_result[1]  # e.g. TIER0_SANCTIONS_HIT
                if tier0_fired
                else "LOW_CONFIDENCE"
                if confidence < self.confidence_policy.low_confidence_threshold
                else "ESCALATION_REVIEW"
            )
            await self.human_review_repository.enqueue(
                triage_result=result,
                reason=reason,
                snapshot={
                    "category": category.value,
                    "priority": priority.value,
                    "escalation_risk": escalation_risk.value,
                    "assigned_team": assigned_team,
                    "confidence": confidence,
                    "model_version": model_version,
                    "tier0_fired": tier0_fired,
                    "llm_used": llm_features is not None,
                    "decision_path": decision_path,
                },
                risk_decision_id=risk_decision.id,
            )

