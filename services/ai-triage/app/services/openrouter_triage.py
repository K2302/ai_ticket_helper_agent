import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.domain.models import Category, EscalationRisk, Priority, TicketCreatedEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmTriagePrediction:
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

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def predict(self, ticket: TicketCreatedEvent) -> LlmTriagePrediction | None:
        if not self.enabled:
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
                        "Classify support tickets. Return only JSON with keys: "
                        "category, priority, escalation_risk, confidence. "
                        "Allowed category values: Billing, Technical Support, Account Access, Bug Report, General Query. "
                        "Allowed priority values: Low, Medium, High, Urgent. "
                        "Allowed escalation_risk values: Low, Medium, High. "
                        "confidence must be a number from 0 to 1.\n"
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
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if content is None:
                return None
            parsed = self._parse_json(content)
            return LlmTriagePrediction(
                category=Category(parsed["category"]),
                priority=Priority(parsed["priority"]),
                escalation_risk=EscalationRisk(parsed["escalation_risk"]),
                confidence=self._clamp_confidence(parsed["confidence"]),
                model_version=f"openrouter:{self.model}",
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            logger.warning("OpenRouter triage failed; using rules fallback: %s", exc)
            return None

    def _parse_json(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    def _clamp_confidence(self, value) -> float:
        return round(max(0.0, min(1.0, float(value))), 2)
