"""
Risk scoring service: fuses triage signals into a 0-1 risk score,
applies policy rules, persists full RiskDecision record with
rule_version + prompt_version for audit/replay.
"""
import hashlib
import json
import logging
from uuid import UUID, uuid4

from app.domain.models import (
    AuditAction,
    Category,
    EscalationRisk,
    ModelRegistry,
    Priority,
    RiskDecision,
    RiskDecisionOutcome,
    TicketCreatedEvent,
    TriageResult,
)
from app.infrastructure.repositories import (
    AuditLogRepository,
    ModelRegistryRepository,
    RiskDecisionRepository,
    ThresholdConfigRepository,
)
from app.services.feature_extractor import FeatureExtractor, FeatureVector
from app.services.openrouter_triage import PROMPT_VERSION
from app.services.policy_engine import RULE_VERSION, PolicyEngine, score_to_decision

logger = logging.getLogger(__name__)


class RiskScoringService:
    def __init__(
        self,
        risk_decision_repo: RiskDecisionRepository,
        model_registry_repo: ModelRegistryRepository,
        threshold_config_repo: ThresholdConfigRepository,
        audit_repo: AuditLogRepository,
        feature_extractor: FeatureExtractor,
        policy_engine: PolicyEngine,
    ) -> None:
        self.risk_decision_repo = risk_decision_repo
        self.model_registry_repo = model_registry_repo
        self.threshold_config_repo = threshold_config_repo
        self.audit_repo = audit_repo
        self.feature_extractor = feature_extractor
        self.policy_engine = policy_engine

    async def decide(
        self,
        ticket: TicketCreatedEvent,
        triage_result: TriageResult,
        features: FeatureVector | None = None,
    ) -> RiskDecision:
        # Re-extract features if caller did not supply them (replay path)
        if features is None:
            features = self.feature_extractor.extract(ticket)

        model_score = self._fuse_score(triage_result, features)
        segment = self._derive_segment(features)

        thresholds = await self.threshold_config_repo.get_for_segment(segment)
        block_t = thresholds.block_threshold if thresholds else 0.80
        review_t = thresholds.review_threshold if thresholds else 0.50

        primary_model = await self.model_registry_repo.get_primary()

        # Tier-0 re-check: hard signals must always produce BLOCK/REVIEW in the
        # risk decision regardless of model score (belt-and-suspenders after
        # triage_service already used them to skip the LLM).
        tier0_result = self.policy_engine.evaluate_tier0(features)
        if tier0_result is not None:
            decision, reason_code, policy_override, policy_rule = tier0_result
        else:
            # Tier-1 contextual rules
            policy_result = self.policy_engine.evaluate(
                features,
                triage_result.category,
                triage_result.priority,
                triage_result.escalation_risk,
                model_score,
            )
            if policy_result is not None:
                decision, reason_code, policy_override, policy_rule = policy_result
            else:
                decision, reason_code = score_to_decision(model_score, block_t, review_t)
                policy_override = False
                policy_rule = None

        feature_dict = features.to_dict()
        feature_hash = hashlib.sha256(
            json.dumps(feature_dict, sort_keys=True).encode()
        ).hexdigest()

        # Determine which prompt version was involved (None if rules-only path)
        prompt_version: str | None = (
            PROMPT_VERSION if triage_result.model_version.startswith("openrouter:") else None
        )

        explainability = {
            "model_score": model_score,
            "block_threshold": block_t,
            "review_threshold": review_t,
            "segment": segment,
            "policy_override": policy_override,
            "policy_rule": policy_rule,
            "rule_version": RULE_VERSION,
            "prompt_version": prompt_version,
            "triage_confidence": triage_result.confidence,
            "triage_priority": triage_result.priority.value,
            "triage_escalation_risk": triage_result.escalation_risk.value,
        }

        risk_decision = await self.risk_decision_repo.create(
            ticket_id=ticket.ticket_id,
            triage_result_id=triage_result.id,
            correlation_id=ticket.correlation_id or uuid4(),
            model_registry_id=primary_model.id if primary_model else None,
            decision=decision,
            reason_code=reason_code,
            score=model_score,
            policy_override=policy_override,
            policy_rule=policy_rule,
            feature_snapshot=feature_dict,
            feature_snapshot_hash=feature_hash,
            explainability=explainability,
            model_version=primary_model.version if primary_model else triage_result.model_version,
            rule_version=RULE_VERSION,
            prompt_version=prompt_version,
        )

        await self.audit_repo.create(
            ticket_id=ticket.ticket_id,
            correlation_id=ticket.correlation_id,
            actor="risk-scoring-service",
            action=AuditAction.RISK_DECISION_MADE,
            details={
                "risk_decision_id": str(risk_decision.id),
                "decision": decision.value,
                "reason_code": reason_code,
                "score": model_score,
                "policy_override": policy_override,
                "rule_version": RULE_VERSION,
                "prompt_version": prompt_version,
            },
        )

        return risk_decision

    def _fuse_score(self, triage: TriageResult, features: FeatureVector) -> float:
        """
        Combine triage confidence (inverted) with priority/escalation signals
        into a 0-1 risk score.  Higher = riskier.
        """
        base = 1.0 - triage.confidence  # low confidence → higher risk

        priority_bump = {
            "Low": 0.0,
            "Medium": 0.05,
            "High": 0.15,
            "Urgent": 0.30,
        }.get(triage.priority.value, 0.0)

        escalation_bump = {
            "Low": 0.0,
            "Medium": 0.10,
            "High": 0.25,
        }.get(triage.escalation_risk.value, 0.0)

        urgency_bonus = 0.10 if features.has_urgency_keywords else 0.0

        raw = base + priority_bump + escalation_bump + urgency_bonus
        return round(min(1.0, max(0.0, raw)), 4)

    def _derive_segment(self, features: FeatureVector) -> str:
        """
        Return the most-specific single segment key for threshold lookup.
        Priority order: new_account > VIP > PREMIUM > CROSS_BORDER > default.
        Keys must match rows in threshold_config and _SEGMENT_DEFAULTS.
        """
        if features.new_account:
            return "new_account"
        if features.customer_tier == "VIP":
            return "tier:VIP"
        if features.customer_tier == "PREMIUM":
            return "tier:PREMIUM"
        if features.customer_region not in ("DOMESTIC", "UNKNOWN", ""):
            return "region:CROSS_BORDER"
        return "default"
