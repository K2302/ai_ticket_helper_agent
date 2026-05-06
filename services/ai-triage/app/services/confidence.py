"""
Phase 3: Human-first routing matrix.

Replaces the single confidence threshold with a segment-aware decision matrix
and operating-mode bias.

Operating modes
---------------
strict_review (fintech v1 default):
  Any uncertainty OR high-risk segment → REVIEW.
  Applies additional bias rules on top of base thresholds.
standard:
  Use raw per-segment thresholds only, no extra bias.

Segment override thresholds
---------------------------
Loaded from ThresholdConfig (DB) when available; these in-code defaults apply
otherwise so the service is operational without DB rows.

  high-value / PREMIUM tier  : review_threshold lowered to 0.40
  cross-border / non-DOMESTIC: review_threshold lowered to 0.45
  new-account                : review_threshold lowered to 0.35
  default                    : review_threshold = 0.50, block_threshold = 0.80
"""
from __future__ import annotations

from app.domain.models import EscalationRisk, OperatingMode, Priority
from app.services.feature_extractor import FeatureVector


# In-code segment threshold defaults (overridden by DB ThresholdConfig rows)
_SEGMENT_DEFAULTS: dict[str, dict[str, float]] = {
    "tier:PREMIUM":       {"review_threshold": 0.40, "block_threshold": 0.80},
    "tier:VIP":           {"review_threshold": 0.35, "block_threshold": 0.75},
    "region:CROSS_BORDER":{"review_threshold": 0.45, "block_threshold": 0.80},
    "new_account":        {"review_threshold": 0.35, "block_threshold": 0.75},
    "default":            {"review_threshold": 0.50, "block_threshold": 0.80},
}


def _thresholds_for(features: FeatureVector | None) -> tuple[float, float]:
    """Return (review_threshold, block_threshold) for the given feature vector."""
    if features is None:
        d = _SEGMENT_DEFAULTS["default"]
        return d["review_threshold"], d["block_threshold"]

    # New accounts get the tightest thresholds (highest review rate)
    if features.new_account:
        d = _SEGMENT_DEFAULTS["new_account"]
        return d["review_threshold"], d["block_threshold"]

    # New accounts get tightest thresholds (highest review rate)
    if features.new_account:
        d = _SEGMENT_DEFAULTS["new_account"]
        return d["review_threshold"], d["block_threshold"]

    tier_key = f"tier:{features.customer_tier}"
    if tier_key in _SEGMENT_DEFAULTS:
        d = _SEGMENT_DEFAULTS[tier_key]
        return d["review_threshold"], d["block_threshold"]

    if features.customer_region not in ("DOMESTIC", "UNKNOWN", ""):
        d = _SEGMENT_DEFAULTS["region:CROSS_BORDER"]
        return d["review_threshold"], d["block_threshold"]

    d = _SEGMENT_DEFAULTS["default"]
    return d["review_threshold"], d["block_threshold"]


class ConfidencePolicy:
    def __init__(
        self,
        low_confidence_threshold: float,
        operating_mode: OperatingMode = OperatingMode.STRICT_REVIEW,
    ) -> None:
        self.low_confidence_threshold = low_confidence_threshold
        self.operating_mode = operating_mode

    def score(
        self,
        category_confidence: float,
        priority_confidence: float,
        escalation_confidence: float,
    ) -> float:
        return round(
            (category_confidence * 0.45)
            + (priority_confidence * 0.35)
            + (escalation_confidence * 0.20),
            2,
        )

    def requires_review(
        self,
        confidence: float,
        priority: Priority,
        escalation_risk: EscalationRisk,
        features: FeatureVector | None = None,
    ) -> bool:
        """
        Phase 3 decision matrix:
        1. Derive per-segment thresholds.
        2. Confidence below review_threshold → REVIEW.
        3. strict_review mode: Tier-0 signals, high-risk segment, or high
           escalation risk bias uncertain cases to REVIEW.
        4. Any urgent/high-escalation regardless of mode.
        """
        review_t, _ = _thresholds_for(features)

        # Base: confidence below segment review threshold
        if confidence < review_t:
            return True

        # Hard triggers regardless of operating mode
        if priority == Priority.URGENT or escalation_risk == EscalationRisk.HIGH:
            return True

        # strict_review extra bias
        if self.operating_mode == OperatingMode.STRICT_REVIEW:
            # Any Tier-0 signal present → always REVIEW (belt-and-suspenders)
            if features is not None and (
                features.sanctions_hit
                or features.impossible_travel
                or features.velocity_breach
                or features.auth_failure_burst
                or features.device_compromised
            ):
                return True

            # High-value / high-risk segments with medium priority or medium
            # escalation risk are biased to review in strict mode
            if features is not None:
                high_value = features.customer_tier in ("PREMIUM", "VIP")
                cross_border = features.customer_region not in ("DOMESTIC", "UNKNOWN", "")
                if (high_value or cross_border) and (
                    priority == Priority.HIGH
                    or escalation_risk == EscalationRisk.MEDIUM
                ):
                    return True

                # New accounts: review on any non-trivial priority
                if features.new_account and priority != Priority.LOW:
                    return True

        return False
