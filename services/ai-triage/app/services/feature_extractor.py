from dataclasses import dataclass

from app.domain.models import Category, EscalationRisk, Priority, TicketCreatedEvent


@dataclass(frozen=True)
class FeatureVector:
    ticket_id_str: str
    channel: str
    title_length: int
    description_length: int
    has_billing_keywords: bool
    has_account_keywords: bool
    has_technical_keywords: bool
    has_urgency_keywords: bool
    customer_tier: str
    customer_region: str
    category_hint: str | None

    # ── Tier-0 fintech hard-signal fields ──────────────────────────────────
    # Caller must populate these from trusted upstream signals before calling
    # the policy engine.  Default False = signal absent / not provided.
    sanctions_hit: bool = False          # ticket entity on watchlist/sanctions list
    impossible_travel: bool = False      # login-geo inconsistent with prior session
    velocity_breach: bool = False        # transaction/request rate exceeds cap
    auth_failure_burst: bool = False     # N auth failures in short window
    device_compromised: bool = False     # device risk score or known-bad device ID
    new_account: bool = False            # account created within 30 days → tightest thresholds

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "title_length": self.title_length,
            "description_length": self.description_length,
            "has_billing_keywords": self.has_billing_keywords,
            "has_account_keywords": self.has_account_keywords,
            "has_technical_keywords": self.has_technical_keywords,
            "has_urgency_keywords": self.has_urgency_keywords,
            "customer_tier": self.customer_tier,
            "customer_region": self.customer_region,
            "category_hint": self.category_hint,
            # Tier-0 signals included in the feature snapshot for audit/replay
            "sanctions_hit": self.sanctions_hit,
            "impossible_travel": self.impossible_travel,
            "velocity_breach": self.velocity_breach,
            "auth_failure_burst": self.auth_failure_burst,
            "device_compromised": self.device_compromised,
            "new_account": self.new_account,
        }


_BILLING_KW = frozenset(["billing", "invoice", "charge", "payment", "refund", "subscription"])
_ACCOUNT_KW = frozenset(["login", "password", "account", "access", "locked", "2fa", "mfa"])
_TECHNICAL_KW = frozenset(["error", "crash", "bug", "broken", "fail", "timeout", "slow"])
_URGENCY_KW = frozenset(["urgent", "asap", "critical", "immediately", "emergency", "blocked"])


class FeatureExtractor:
    def extract(self, ticket: TicketCreatedEvent) -> FeatureVector:
        text = f"{ticket.title} {ticket.description}".lower()
        words = set(text.split())
        metadata = ticket.customer_metadata or {}

        # Tier-0 signals: sourced from trusted metadata provided by upstream
        # risk/fraud systems.  Keys are snake_case booleans; absent → False.
        risk_signals = metadata.get("risk_signals") or {}

        return FeatureVector(
            ticket_id_str=str(ticket.ticket_id),
            channel=ticket.channel,
            title_length=len(ticket.title),
            description_length=len(ticket.description),
            has_billing_keywords=bool(words & _BILLING_KW),
            has_account_keywords=bool(words & _ACCOUNT_KW),
            has_technical_keywords=bool(words & _TECHNICAL_KW),
            has_urgency_keywords=bool(words & _URGENCY_KW),
            customer_tier=str(metadata.get("tier", "STANDARD")),
            customer_region=str(metadata.get("region", "UNKNOWN")),
            category_hint=str(metadata.get("category_hint")) if metadata.get("category_hint") else None,
            sanctions_hit=bool(risk_signals.get("sanctions_hit", False)),
            impossible_travel=bool(risk_signals.get("impossible_travel", False)),
            velocity_breach=bool(risk_signals.get("velocity_breach", False)),
            auth_failure_burst=bool(risk_signals.get("auth_failure_burst", False)),
            device_compromised=bool(risk_signals.get("device_compromised", False)),
            new_account=(
                bool(risk_signals.get("new_account", False))
                or int(metadata.get("account_age_days", 365)) < 30
            ),
        )
