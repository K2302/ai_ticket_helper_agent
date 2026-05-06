import json
import logging
import time
from dataclasses import dataclass
from enum import StrEnum

import httpx

from app.core.config import Settings
from app.domain.models import Category, EscalationRisk, Priority, TicketCreatedEvent

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 8.0           # hard budget per LLM call
_CB_FAILURE_THRESHOLD = 5        # open circuit after N consecutive failures
_CB_RECOVERY_SECONDS = 60.0      # half-open retry window

# Phase 2: prompt version pinned here so it propagates to every RiskDecision
PROMPT_VERSION = "triage-prompt-v1.0.0"

# Allowed enum values for strict validation — LLM must return exactly one of these
_VALID_CATEGORIES = {c.value for c in Category}
_VALID_PRIORITIES = {p.value for p in Priority}
_VALID_ESCALATION_RISKS = {e.value for e in EscalationRisk}
_REQUIRED_KEYS = frozenset({"category", "priority", "escalation_risk", "confidence"})


class _CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True)
class LlmTriageFeatures:
    """
    LLM output: structured feature extraction only.
    The LLM NEVER writes a final decision — it provides enriched signals
    that feed the deterministic policy engine.
    """
    category: Category
    priority: Priority
    escalation_risk: EscalationRisk
    confidence: float
    model_version: str


class OpenRouterTriageClient:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.http_referer = settings.openrouter_http_referer
        self.app_title = settings.openrouter_app_title

        self._cb_state = _CircuitState.CLOSED
        self._cb_failures = 0
        self._cb_opened_at: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_key(self) -> str:
        return f"openrouter:{self.model}"

    def _check_circuit(self) -> bool:
        """Return True if the call is allowed."""
        if self._cb_state == _CircuitState.CLOSED:
            return True
        if self._cb_state == _CircuitState.OPEN:
            if time.monotonic() - self._cb_opened_at >= _CB_RECOVERY_SECONDS:
                self._cb_state = _CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN: allow one probe
        return True

    def _record_success(self) -> None:
        self._cb_state = _CircuitState.CLOSED
        self._cb_failures = 0

    def _record_failure(self) -> None:
        self._cb_failures += 1
        if self._cb_failures >= _CB_FAILURE_THRESHOLD:
            self._cb_state = _CircuitState.OPEN
            self._cb_opened_at = time.monotonic()
            logger.error("Circuit OPENED for provider %s after %d failures", self.provider_key, self._cb_failures)

    def is_circuit_open(self) -> bool:
        return self._cb_state == _CircuitState.OPEN

    async def extract_features(self, ticket: TicketCreatedEvent) -> LlmTriageFeatures | None:
        """
        Phase 2 contract: LLM extracts structured classification features only.
        Returns None on any failure (circuit open, timeout, parse error, schema
        violation) — the caller MUST fall back to rules-only path.
        """
        if not self.enabled:
            return None
        if not self._check_circuit():
            logger.warning("Circuit OPEN for %s — rules-only fallback", self.provider_key)
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer

        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 250,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Extract structured classification features from the support ticket below. "
                        "Return ONLY a JSON object with exactly these keys: "
                        "category, priority, escalation_risk, confidence. "
                        f"Allowed category values (exact strings): {sorted(_VALID_CATEGORIES)}. "
                        f"Allowed priority values (exact strings): {sorted(_VALID_PRIORITIES)}. "
                        f"Allowed escalation_risk values (exact strings): {sorted(_VALID_ESCALATION_RISKS)}. "
                        "confidence must be a number between 0 and 1. "
                        "Do NOT make a final decision — only classify features.\n"
                        f"Ticket: {json.dumps({
                            'title': ticket.title,
                            'description': ticket.description,
                            'customer_metadata': ticket.customer_metadata,
                            'channel': ticket.channel,
                        })}"
                    ),
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if content is None:
                logger.warning("OpenRouter returned null content for %s", self.provider_key)
                self._record_failure()
                return None
            parsed = self._parse_and_validate(content)
            if parsed is None:
                # Schema validation failed — treat as failure, use rules fallback
                self._record_failure()
                return None
            result = LlmTriageFeatures(
                category=Category(parsed["category"]),
                priority=Priority(parsed["priority"]),
                escalation_risk=EscalationRisk(parsed["escalation_risk"]),
                confidence=self._clamp_confidence(parsed["confidence"]),
                model_version=f"openrouter:{self.model}",
            )
            self._record_success()
            return result
        except (httpx.HTTPError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("OpenRouter request failed; rules fallback: %s", exc)
            self._record_failure()
            return None

    def _parse_and_validate(self, content: str) -> dict | None:
        """
        Phase 2 strict validation:
        1. Must parse as valid JSON.
        2. Must contain all required keys.
        3. category/priority/escalation_risk must be exact enum values.
        4. confidence must be numeric.
        Any violation returns None → rules fallback.
        """
        try:
            raw = self._strip_markdown_fence(content)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM response is not valid JSON; rules fallback: %s", exc)
            return None

        if not isinstance(parsed, dict):
            logger.warning("LLM response is not a JSON object; rules fallback")
            return None

        missing = _REQUIRED_KEYS - parsed.keys()
        if missing:
            logger.warning("LLM response missing required keys %s; rules fallback", missing)
            return None

        if parsed["category"] not in _VALID_CATEGORIES:
            logger.warning(
                "LLM returned invalid category %r (allowed: %s); rules fallback",
                parsed["category"], _VALID_CATEGORIES,
            )
            return None

        if parsed["priority"] not in _VALID_PRIORITIES:
            logger.warning(
                "LLM returned invalid priority %r (allowed: %s); rules fallback",
                parsed["priority"], _VALID_PRIORITIES,
            )
            return None

        if parsed["escalation_risk"] not in _VALID_ESCALATION_RISKS:
            logger.warning(
                "LLM returned invalid escalation_risk %r (allowed: %s); rules fallback",
                parsed["escalation_risk"], _VALID_ESCALATION_RISKS,
            )
            return None

        try:
            float(parsed["confidence"])
        except (TypeError, ValueError):
            logger.warning("LLM returned non-numeric confidence %r; rules fallback", parsed["confidence"])
            return None

        return parsed

    def _strip_markdown_fence(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return text.strip()

    def _clamp_confidence(self, value) -> float:
        return round(max(0.0, min(1.0, float(value))), 2)

    # ── Back-compat alias removed — callers must use extract_features() ──────
