package com.aihumanloop.ingestion.dto;

import com.aihumanloop.ingestion.domain.TicketChannel;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.Map;

public record CreateTicketRequest(
        @NotBlank @Size(max = 200) String title,
        @NotBlank String description,
        @NotNull Map<String, Object> customerMetadata,
        @NotNull TicketChannel channel,
        @Size(max = 200) String idempotencyKey
) {
}
