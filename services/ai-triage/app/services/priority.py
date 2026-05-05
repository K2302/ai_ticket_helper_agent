from app.domain.models import Priority, TicketCreatedEvent


class PriorityPredictor:
    def predict(self, ticket: TicketCreatedEvent) -> tuple[Priority, float]:
        text = f"{ticket.title} {ticket.description}".lower()
        urgent_terms = ["down", "outage", "security", "breach", "data loss", "cannot work", "blocked"]
        high_terms = ["500", "failed", "crash", "payment failed", "production", "vip"]
        medium_terms = ["error", "unable", "issue", "slow", "timeout"]

        if any(term in text for term in urgent_terms):
            return Priority.URGENT, 0.90
        if any(term in text for term in high_terms):
            return Priority.HIGH, 0.82
        if any(term in text for term in medium_terms):
            return Priority.MEDIUM, 0.74
        return Priority.LOW, 0.68
