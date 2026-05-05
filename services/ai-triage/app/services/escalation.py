from app.domain.models import EscalationRisk, TicketCreatedEvent


class EscalationScorer:
    def score(self, ticket: TicketCreatedEvent) -> tuple[EscalationRisk, float]:
        text = f"{ticket.title} {ticket.description}".lower()
        high_terms = ["legal", "lawsuit", "angry", "cancel", "breach", "security", "outage", "vip"]
        medium_terms = ["refund", "complaint", "frustrated", "production", "blocked"]

        if any(term in text for term in high_terms):
            return EscalationRisk.HIGH, 0.88
        if any(term in text for term in medium_terms):
            return EscalationRisk.MEDIUM, 0.76
        return EscalationRisk.LOW, 0.78
