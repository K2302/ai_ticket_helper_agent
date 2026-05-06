from __future__ import annotations

from app.domain.models import EscalationRisk, TicketCreatedEvent
from app.services.feature_extractor import FeatureVector


class EscalationScorer:
    def score(
        self,
        ticket: TicketCreatedEvent,
        features: FeatureVector | None = None,
    ) -> tuple[EscalationRisk, float]:
        # Phase 3: Tier-0 hard signals take precedence over text classification.
        # sanctions / device compromise → definite HIGH escalation.
        if features is not None:
            if features.sanctions_hit or features.device_compromised:
                return EscalationRisk.HIGH, 1.0
            if (
                features.impossible_travel
                or features.velocity_breach
                or features.auth_failure_burst
            ):
                return EscalationRisk.HIGH, 0.95

        text = f"{ticket.title} {ticket.description}".lower()
        high_terms = ["legal", "lawsuit", "angry", "cancel", "breach", "security", "outage", "vip"]
        medium_terms = ["refund", "complaint", "frustrated", "production", "blocked"]

        if any(term in text for term in high_terms):
            return EscalationRisk.HIGH, 0.88
        if any(term in text for term in medium_terms):
            return EscalationRisk.MEDIUM, 0.76
        return EscalationRisk.LOW, 0.78
