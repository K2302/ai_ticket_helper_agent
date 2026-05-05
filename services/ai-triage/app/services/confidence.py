from app.domain.models import EscalationRisk, Priority


class ConfidencePolicy:
    def __init__(self, low_confidence_threshold: float) -> None:
        self.low_confidence_threshold = low_confidence_threshold

    def score(self, category_confidence: float, priority_confidence: float, escalation_confidence: float) -> float:
        return round((category_confidence * 0.45) + (priority_confidence * 0.35) + (escalation_confidence * 0.20), 2)

    def requires_review(self, confidence: float, priority: Priority, escalation_risk: EscalationRisk) -> bool:
        if confidence < self.low_confidence_threshold:
            return True
        return priority == Priority.URGENT or escalation_risk == EscalationRisk.HIGH
