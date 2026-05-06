"""
Deterministic policy layer.  Rules run BEFORE (and can override) the model score.

Two tiers:
  Tier-0  — hard fintech signals (sanctions, impossible travel, velocity,
            auth failures, device compromise).  A Tier-0 match immediately
            returns BLOCK or REVIEW and SKIPS the LLM entirely.
  Tier-1  — contextual rules evaluated after LLM feature extraction.

Returns (decision, reason_code, policy_override, policy_rule) or None.
"""

RULE_VERSION = "policy-v1.0.0"

from app.domain.models import Category, EscalationRisk, Priority, RiskDecisionOutcome
from app.services.feature_extractor import FeatureVector


class PolicyEngine:
    """
    Hard rules evaluated in priority order.  First matching rule wins.
    Returns None if no rule matches — fall through to model score.
    """

    # ── Tier-0: fintech hard signals ────────────────────────────────────────

    def evaluate_tier0(
        self,
        features: FeatureVector,
    ) -> tuple[RiskDecisionOutcome, str, bool, str] | None:
        """
        Evaluated BEFORE any LLM call.  A match skips LLM entirely.
        Returns (decision, reason_code, policy_override=True, rule_name) or None.
        """
        # T0-R1: entity on sanctions / watchlist → always BLOCK
        if features.sanctions_hit:
            return (
                RiskDecisionOutcome.BLOCK,
                "TIER0_SANCTIONS_HIT",
                True,
                "T0R1_SANCTIONS_HIT",
            )

        # T0-R2: impossible travel (geo anomaly) → REVIEW for human verification
        if features.impossible_travel:
            return (
                RiskDecisionOutcome.REVIEW,
                "TIER0_IMPOSSIBLE_TRAVEL",
                True,
                "T0R2_IMPOSSIBLE_TRAVEL",
            )

        # T0-R3: transaction/request velocity cap breached → REVIEW
        if features.velocity_breach:
            return (
                RiskDecisionOutcome.REVIEW,
                "TIER0_VELOCITY_BREACH",
                True,
                "T0R3_VELOCITY_BREACH",
            )

        # T0-R4: authentication failure burst → REVIEW (possible account takeover)
        if features.auth_failure_burst:
            return (
                RiskDecisionOutcome.REVIEW,
                "TIER0_AUTH_FAILURE_BURST",
                True,
                "T0R4_AUTH_FAILURE_BURST",
            )

        # T0-R5: device compromise indicator → BLOCK
        if features.device_compromised:
            return (
                RiskDecisionOutcome.BLOCK,
                "TIER0_DEVICE_COMPROMISED",
                True,
                "T0R5_DEVICE_COMPROMISED",
            )

        return None  # no Tier-0 match; proceed to LLM + Tier-1

    # ── Tier-1: contextual rules (run after LLM extraction) ─────────────────

    def evaluate(
        self,
        features: FeatureVector,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        model_score: float,
    ) -> tuple[RiskDecisionOutcome, str, bool, str] | None:
        """
        Returns (decision, reason_code, policy_override=True, rule_name) or None.
        """
        # R1: urgent + high escalation risk → always BLOCK
        if priority == Priority.URGENT and escalation_risk == EscalationRisk.HIGH:
            return (
                RiskDecisionOutcome.BLOCK,
                "POLICY_URGENT_HIGH_ESCALATION",
                True,
                "R1_URGENT_HIGH_ESCALATION",
            )

        # R2: billing + urgency keywords + premium tier → REVIEW (protect revenue)
        if (
            category == Category.BILLING
            and features.has_urgency_keywords
            and features.customer_tier == "PREMIUM"
        ):
            return (
                RiskDecisionOutcome.REVIEW,
                "POLICY_BILLING_URGENCY_PREMIUM",
                True,
                "R2_BILLING_URGENCY_PREMIUM",
            )

        # R3: account access + urgent → REVIEW
        if category == Category.ACCOUNT_ACCESS and priority == Priority.URGENT:
            return (
                RiskDecisionOutcome.REVIEW,
                "POLICY_ACCOUNT_URGENT",
                True,
                "R3_ACCOUNT_URGENT",
            )

        # R4: very short description (likely spam/noise) + low priority → APPROVE
        if features.description_length < 20 and priority == Priority.LOW:
            return (
                RiskDecisionOutcome.APPROVE,
                "POLICY_LOW_EFFORT_TICKET",
                True,
                "R4_SHORT_LOW_PRIORITY",
            )

        return None  # no policy match; use model score


def score_to_decision(
    model_score: float,
    block_threshold: float = 0.80,
    review_threshold: float = 0.50,
) -> tuple[RiskDecisionOutcome, str]:
    if model_score >= block_threshold:
        return RiskDecisionOutcome.BLOCK, "MODEL_HIGH_RISK_SCORE"
    if model_score >= review_threshold:
        return RiskDecisionOutcome.REVIEW, "MODEL_MEDIUM_RISK_SCORE"
    return RiskDecisionOutcome.APPROVE, "MODEL_LOW_RISK_SCORE"
