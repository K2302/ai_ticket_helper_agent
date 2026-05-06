"""
Config-driven 6-node SaaS support triage decision tree.

Design principles
-----------------
* The tree is defined as a plain Python dict (``TRIAGE_TREE``) so it can be
  serialised to JSON and injected verbatim into the LLM prompt — making the
  system prompt configuration-driven rather than hard-coded text.
* ``evaluate_tree()`` runs the same tree deterministically (no LLM) and is
  used by:
    - TicketClassifier for the rules-only fallback path.
    - OpenRouterTriageClient to verify the LLM's ``decision_path`` is valid.
* ``TREE_VERSION`` is propagated through every RiskDecision for audit/replay.

Tree structure
--------------
Node 1  Identity & Access          → Account Access / Account Support
Node 2  Financial / Commercial     → branch to Node 3
Node 3  Billing Depth (child of 2) → Billing / Billing Support (priority High/Medium)
Node 4  System Health              → Technical Support / Engineering L1
Node 5  Product / Feature          → General Query / Product & Success
Node 6  Sentiment / Urgency filter → EscalationRisk.HIGH override (any category)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import Category, EscalationRisk, Priority

TREE_VERSION = "tree-v1.0.0"

# ---------------------------------------------------------------------------
# Canonical tree definition – injected into the LLM prompt as JSON
# ---------------------------------------------------------------------------
TRIAGE_TREE: dict = {
    "version": TREE_VERSION,
    "description": (
        "6-node hierarchical decision tree for SaaS support triage. "
        "Walk each node in order. Record each visited node id in decision_path. "
        "Stop walking when a terminal leaf is reached."
    ),
    "nodes": [
        {
            "id": 1,
            "name": "Identity & Access",
            "criteria": (
                "User mentions being locked out, password reset, 403 Forbidden, "
                "MFA issues, or 2FA issues."
            ),
            "example_signals": ["locked out", "password reset", "403", "forbidden",
                                 "mfa", "2fa", "login failed", "can't log in"],
            "if_yes": {
                "terminal": True,
                "category": "Account Access",
                "team": "Account Support",
                "priority_hint": "escalate to High if also mentions urgency",
            },
            "if_no": "proceed to node 2",
        },
        {
            "id": 2,
            "name": "Financial / Commercial Intent",
            "criteria": (
                "Ticket mentions refund, invoice, pricing, subscription, or charge."
            ),
            "example_signals": ["refund", "invoice", "pricing", "subscription",
                                 "charge", "billing", "payment", "overdue"],
            "if_yes": "proceed to node 3 (Billing Depth)",
            "if_no": "proceed to node 4",
        },
        {
            "id": 3,
            "name": "Billing Depth",
            "parent_node": 2,
            "criteria": (
                "Ticket mentions a failed payment or overcharge specifically — "
                "revenue is directly at risk."
            ),
            "example_signals": ["failed payment", "overcharge", "double charged",
                                 "incorrect charge", "charged twice", "wrong amount"],
            "if_yes": {
                "terminal": True,
                "category": "Billing",
                "team": "Billing Support",
                "priority": "High",
                "note": "Revenue at risk — treat as High priority.",
            },
            "if_no": {
                "terminal": True,
                "category": "Billing",
                "team": "Billing Support",
                "priority": "Medium",
            },
        },
        {
            "id": 4,
            "name": "System Health",
            "criteria": (
                "Description mentions 500 Internal Server Error, system down, "
                "API timeout, or latency/outage."
            ),
            "example_signals": ["500", "internal server error", "system down",
                                 "api timeout", "latency", "outage", "not responding"],
            "if_yes": {
                "terminal": True,
                "category": "Technical Support",
                "team": "Engineering L1",
                "priority": "High",
                "note": "Critical — route directly to Engineering L1.",
            },
            "if_no": "proceed to node 5",
        },
        {
            "id": 5,
            "name": "Product / Feature",
            "criteria": (
                "User is asking 'how-to' or requesting a new capability or feature."
            ),
            "example_signals": ["how to", "how do i", "feature request",
                                 "can you add", "is it possible", "documentation",
                                 "tutorial"],
            "if_yes": {
                "terminal": True,
                "category": "General Query",
                "team": "Product & Success",
                "priority": "Low",
            },
            "if_no": "proceed to node 6",
        },
        {
            "id": 6,
            "name": "Sentiment / Urgency Filter",
            "criteria": (
                "Tone is highly frustrated or ticket mentions leaving, canceling, "
                "or any threatening language."
            ),
            "example_signals": ["cancel", "canceling", "leaving", "furious",
                                 "unacceptable", "legal action", "terrible service",
                                 "switch provider"],
            "if_yes": {
                "terminal": True,
                "escalation_override": "High",
                "note": (
                    "Flag as High EscalationRisk regardless of category. "
                    "Maintain routing determined by prior nodes."
                ),
            },
            "if_no": {
                "terminal": True,
                "note": "Default routing — no escalation override.",
            },
        },
    ],
}

# ---------------------------------------------------------------------------
# Keyword sets for deterministic evaluation (rules-only / fallback path)
# ---------------------------------------------------------------------------
_N1_KW = frozenset(["locked", "lock out", "lockout", "password reset", "403",
                     "forbidden", "mfa", "2fa", "login failed", "can't log in",
                     "cant log in", "cannot log in"])
_N2_KW = frozenset(["refund", "invoice", "pricing", "subscription", "charge",
                     "billing", "payment", "overdue"])
_N3_KW = frozenset(["failed payment", "overcharge", "double charged",
                     "incorrect charge", "charged twice", "wrong amount"])
_N4_KW = frozenset(["500", "internal server error", "system down", "api timeout",
                     "latency", "outage", "not responding", "api error"])
_N5_KW = frozenset(["how to", "how do i", "feature request", "can you add",
                     "is it possible", "documentation", "tutorial"])
_N6_KW = frozenset(["cancel", "canceling", "cancellation", "leaving", "furious",
                     "unacceptable", "legal action", "terrible service",
                     "switch provider"])


@dataclass(frozen=True)
class TreeDecision:
    """Result of running the tree, either deterministically or via LLM."""
    category: Category
    priority: Priority
    escalation_risk: EscalationRisk
    target_team: str
    decision_path: list[int] = field(default_factory=list)

    def path_str(self) -> str:
        return " → ".join(f"N{n}" for n in self.decision_path)


def evaluate_tree(text: str) -> TreeDecision:
    """
    Deterministic rules-only tree walk — identical logic to the JSON tree above.
    Used in:
      * TicketClassifier (rules fallback when LLM is unavailable).
      * _validate_decision_path() to sanity-check LLM-reported paths.
    """
    t = text.lower()
    path: list[int] = []

    def _match(keywords: frozenset[str]) -> bool:
        return any(kw in t for kw in keywords)

    # ── Node 1: Identity & Access ─────────────────────────────────────────
    path.append(1)
    if _match(_N1_KW):
        return TreeDecision(
            category=Category.ACCOUNT_ACCESS,
            priority=Priority.HIGH if _match(frozenset(["urgent", "asap", "immediately"])) else Priority.MEDIUM,
            escalation_risk=EscalationRisk.LOW,
            target_team="Account Support",
            decision_path=path,
        )

    # ── Node 2: Financial / Commercial ───────────────────────────────────
    path.append(2)
    if _match(_N2_KW):
        # ── Node 3: Billing Depth ─────────────────────────────────────────
        path.append(3)
        if _match(_N3_KW):
            return TreeDecision(
                category=Category.BILLING,
                priority=Priority.HIGH,
                escalation_risk=EscalationRisk.MEDIUM,
                target_team="Billing Support",
                decision_path=path,
            )
        return TreeDecision(
            category=Category.BILLING,
            priority=Priority.MEDIUM,
            escalation_risk=EscalationRisk.LOW,
            target_team="Billing Support",
            decision_path=path,
        )

    # ── Node 4: System Health ─────────────────────────────────────────────
    path.append(4)
    if _match(_N4_KW):
        return TreeDecision(
            category=Category.TECHNICAL_SUPPORT,
            priority=Priority.HIGH,
            escalation_risk=EscalationRisk.HIGH,
            target_team="Engineering L1",
            decision_path=path,
        )

    # ── Node 5: Product / Feature ─────────────────────────────────────────
    path.append(5)
    if _match(_N5_KW):
        return TreeDecision(
            category=Category.GENERAL_QUERY,
            priority=Priority.LOW,
            escalation_risk=EscalationRisk.LOW,
            target_team="Product & Success",
            decision_path=path,
        )

    # ── Node 6: Sentiment / Urgency ───────────────────────────────────────
    path.append(6)
    if _match(_N6_KW):
        return TreeDecision(
            category=Category.GENERAL_QUERY,
            priority=Priority.HIGH,
            escalation_risk=EscalationRisk.HIGH,
            target_team="Customer Support",
            decision_path=path,
        )

    # Exhausted all nodes — general query
    return TreeDecision(
        category=Category.GENERAL_QUERY,
        priority=Priority.LOW,
        escalation_risk=EscalationRisk.LOW,
        target_team="Customer Support",
        decision_path=path,
    )


def validate_decision_path(path: list) -> bool:
    """
    Check that the LLM-reported decision_path is a non-empty list of node ids
    in [1..6] and follows valid tree edges.  Strict but not exhaustive — catches
    obvious hallucinations.
    """
    if not isinstance(path, list) or not path:
        return False
    valid_ids = {1, 2, 3, 4, 5, 6}
    if not all(isinstance(n, int) and n in valid_ids for n in path):
        return False
    # Node 3 can only appear after Node 2
    if 3 in path and path.index(3) > 0 and path[path.index(3) - 1] != 2:
        return False
    return True
