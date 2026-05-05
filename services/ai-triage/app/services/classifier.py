from app.domain.models import Category, TicketCreatedEvent


class TicketClassifier:
    def classify(self, ticket: TicketCreatedEvent) -> tuple[Category, float]:
        text = f"{ticket.title} {ticket.description}".lower()
        rules = [
            (Category.BILLING, ["billing", "invoice", "payment", "refund", "charge", "subscription"]),
            (Category.ACCOUNT_ACCESS, ["login", "password", "reset", "locked", "access", "mfa", "2fa"]),
            (Category.BUG_REPORT, ["bug", "broken", "error", "500", "exception", "crash", "regression"]),
            (Category.TECHNICAL_SUPPORT, ["api", "integration", "timeout", "latency", "webhook", "database"]),
        ]

        best_category = Category.GENERAL_QUERY
        best_hits = 0
        for category, keywords in rules:
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits > best_hits:
                best_category = category
                best_hits = hits

        if best_hits == 0:
            return best_category, 0.45
        if best_hits == 1:
            return best_category, 0.72
        return best_category, min(0.95, 0.78 + (best_hits * 0.06))
