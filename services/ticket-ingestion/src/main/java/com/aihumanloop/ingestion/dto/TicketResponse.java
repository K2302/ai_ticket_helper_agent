package com.aihumanloop.ingestion.dto;

import com.aihumanloop.ingestion.domain.TicketChannel;
import com.aihumanloop.ingestion.domain.TicketStatus;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

public record TicketResponse(
        UUID id,
        String title,
        String description,
        Map<String, Object> customerMetadata,
        TicketChannel channel,
        TicketStatus status,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt
) {
}
