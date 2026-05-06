import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from app.core.config import Settings
from app.domain.models import TicketCreatedEvent
from app.infrastructure.repositories import ProcessedEventRepository
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)

# Retry tiers: (max_attempts, base_delay_seconds)
_TRANSIENT_TIER = (3, 0.5)
_DLQ_THRESHOLD = _TRANSIENT_TIER[0]


class TicketKafkaConsumer:
    def __init__(
        self,
        settings: Settings,
        triage_service: TriageService,
        processed_event_repo: ProcessedEventRepository,
    ) -> None:
        self.settings = settings
        self.triage_service = triage_service
        self.processed_event_repo = processed_event_repo
        self.consumer: AIOKafkaConsumer | None = None
        self.task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            self.settings.ticket_created_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        self._shutdown.clear()
        self.task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        self._shutdown.set()
        if self.task is not None:
            try:
                await asyncio.wait_for(self.task, timeout=10.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
        if self.consumer is not None:
            await self.consumer.commit()
            await self.consumer.stop()

    async def _consume(self) -> None:
        assert self.consumer is not None
        async for message in self.consumer:
            if self._shutdown.is_set():
                break
            await self._handle_with_retry(message)

    async def _handle_with_retry(self, message) -> None:
        max_attempts, base_delay = _TRANSIENT_TIER
        attempt = 0
        while attempt < max_attempts:
            try:
                payload = json.loads(message.value.decode("utf-8"))
                event = self._parse_event(payload)
                idempotency_key = f"{self.settings.kafka_group_id}:{message.topic}:{message.partition}:{message.offset}"

                already_processed = await self.processed_event_repo.is_processed(
                    idempotency_key, self.settings.kafka_group_id
                )
                if already_processed:
                    logger.info("Duplicate event skipped: %s", idempotency_key)
                    await self.consumer.commit()
                    return

                await self.triage_service.triage(event)
                await self.processed_event_repo.mark_processed(
                    idempotency_key, self.settings.kafka_group_id
                )
                await self.consumer.commit()
                return
            except Exception as exc:
                attempt += 1
                if attempt >= max_attempts:
                    logger.error(
                        "Message exhausted retries; routing to DLQ: topic=%s partition=%d offset=%d error=%s",
                        message.topic, message.partition, message.offset, exc,
                    )
                    await self._route_to_dlq(message, exc)
                    await self.consumer.commit()
                    return
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Transient error processing message, retry %d/%d in %.1fs: %s",
                    attempt, max_attempts, delay, exc,
                )
                await asyncio.sleep(delay)

    async def _route_to_dlq(self, message, exc: Exception) -> None:
        """Log DLQ routing; actual DLQ Kafka topic forwarding can be added here."""
        logger.error(
            "DLQ: topic=%s partition=%d offset=%d error=%r payload=%s",
            message.topic,
            message.partition,
            message.offset,
            exc,
            message.value[:500] if message.value else b"",
        )

    def _parse_event(self, payload: dict) -> TicketCreatedEvent:
        return TicketCreatedEvent(
            ticket_id=UUID(payload["ticketId"]),
            title=payload["title"],
            description=payload["description"],
            customer_metadata=payload.get("customerMetadata", {}),
            channel=payload["channel"],
            correlation_id=UUID(payload["correlationId"]) if payload.get("correlationId") else None,
            created_at=self._parse_created_at(payload["createdAt"]),
        )

    def _parse_created_at(self, value) -> datetime:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise ValueError(f"Unsupported createdAt value: {value!r}")
