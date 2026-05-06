"""
Rules-only ticket classifier — uses the config-driven 6-node decision tree
(triage_tree.py) so the deterministic fallback path mirrors exactly the logic
injected into the LLM prompt.

classify() is kept backward-compatible (returns Category + float) so callers
that only need those two values don't change.  Use classify_with_tree() when
you also need the decision_path and target_team hint.
"""
from app.domain.models import Category, TicketCreatedEvent
from app.services.triage_tree import TreeDecision, evaluate_tree

# Confidence calibration for the deterministic path.
# Tree walks are structurally confident when they reach a specific leaf early,
# less confident when they fall through to the generic leaf.
_PATH_CONFIDENCE: dict[tuple[int, ...], float] = {
    (1,):          0.88,   # N1 hit  — very specific access signal
    (1, 2, 3):     0.90,   # N1+N2+N3 (shouldn't happen, but guard)
    (1, 2):        0.82,   # billing after access miss
    (1, 2, 3):     0.92,   # billing depth
    (1, 2, 4):     0.86,   # system health
    (1, 2, 4, 5):  0.78,   # product/feature
    (1, 2, 4, 5, 6): 0.72, # sentiment filter
    (1, 2, 4, 5, 6): 0.60, # exhausted — general query
}
_DEFAULT_CONFIDENCE = 0.65


class TicketClassifier:
    def classify(self, ticket: TicketCreatedEvent) -> tuple[Category, float]:
        """Return (Category, confidence) for the rules-only path."""
        decision = self.classify_with_tree(ticket)
        return decision.category, _path_confidence(decision.decision_path)

    def classify_with_tree(self, ticket: TicketCreatedEvent) -> TreeDecision:
        """Full tree walk — returns category, priority, escalation, team, path."""
        text = f"{ticket.title} {ticket.description}"
        return evaluate_tree(text)


def _path_confidence(path: list[int]) -> float:
    """Longer path = more nodes exhausted = lower confidence."""
    length = len(path)
    if length == 1:
        return 0.88   # hit on first node
    if length == 2:
        return 0.82
    if length == 3:
        return 0.78
    if length == 4:
        return 0.72
    return _DEFAULT_CONFIDENCE
