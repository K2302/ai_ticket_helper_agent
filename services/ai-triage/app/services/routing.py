from app.domain.models import Category, EscalationRisk, Priority


class RoutingEngine:
    def route(self, category: Category, priority: Priority, escalation_risk: EscalationRisk) -> str:
        if escalation_risk == EscalationRisk.HIGH or priority == Priority.URGENT:
            return "Escalations"
        if category == Category.BILLING:
            return "Billing Support"
        if category == Category.ACCOUNT_ACCESS:
            return "Account Support"
        if category in {Category.BUG_REPORT, Category.TECHNICAL_SUPPORT}:
            return "Technical Support"
        return "Customer Support"
