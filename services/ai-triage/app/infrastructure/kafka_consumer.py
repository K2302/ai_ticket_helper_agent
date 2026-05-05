import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from aiokafka import AIOKafkaConsumer

from app.core.config import Settings
from app.domain.models import TicketCreatedEvent
from app.services.triage_service import TriageService


class TicketKafkaConsumer:
    def __init__(self, settings: Settings, triage_service: TriageService) -> None:
        self.settings = settings
        self.triage_service = triage_service
        self.consumer: AIOKafkaConsumer | None = None
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            self.settings.ticket_created_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        self.task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.consumer is not None:
            await self.consumer.stop()

    async def _consume(self) -> None:
        assert self.consumer is not None
        async for message in self.consumer:
            payload = json.loads(message.value.decode("utf-8"))
            await self.triage_service.triage(self._parse_event(payload))
            await self.consumer.commit()

    def _parse_event(self, payload: dict) -> TicketCreatedEvent:
        return TicketCreatedEvent(
            ticket_id=UUID(payload["ticketId"]),
            title=payload["title"],
            description=payload["description"],
            customer_metadata=payload.get("customerMetadata", {}),
            channel=payload["channel"],
            created_at=self._parse_created_at(payload["createdAt"]),
        )

    def _parse_created_at(self, value) -> datetime:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise ValueError(f"Unsupported createdAt value: {value!r}")
