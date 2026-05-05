package com.aihumanloop.ingestion.events;

import com.aihumanloop.ingestion.domain.TicketChannel;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

public record TicketCreatedEvent(
        UUID ticketId,
        String title,
        String description,
        Map<String, Object> customerMetadata,
        TicketChannel channel,
        OffsetDateTime createdAt
) {
}
