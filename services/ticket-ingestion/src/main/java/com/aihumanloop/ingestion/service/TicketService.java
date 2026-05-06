package com.aihumanloop.ingestion.service;

import com.aihumanloop.ingestion.domain.OutboxEvent;
import com.aihumanloop.ingestion.domain.Ticket;
import com.aihumanloop.ingestion.dto.CreateTicketRequest;
import com.aihumanloop.ingestion.dto.TicketResponse;
import com.aihumanloop.ingestion.repository.OutboxEventRepository;
import com.aihumanloop.ingestion.repository.TicketRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketService {
    private final TicketRepository ticketRepository;
    private final OutboxEventRepository outboxEventRepository;
    private final ObjectMapper objectMapper;

    public TicketService(
            TicketRepository ticketRepository,
            OutboxEventRepository outboxEventRepository,
            ObjectMapper objectMapper
    ) {
        this.ticketRepository = ticketRepository;
        this.outboxEventRepository = outboxEventRepository;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public TicketResponse create(CreateTicketRequest request) {
        Ticket ticket = new Ticket();
        ticket.setTitle(request.title());
        ticket.setDescription(request.description());
        ticket.setCustomerMetadata(request.customerMetadata());
        ticket.setChannel(request.channel());
        ticket.setIdempotencyKey(request.idempotencyKey());

        Ticket saved = ticketRepository.saveAndFlush(ticket);

        // Write outbox in same transaction — no dual-write risk
        OutboxEvent outboxEvent = new OutboxEvent();
        outboxEvent.setAggregateId(saved.getId());
        outboxEvent.setAggregateType("Ticket");
        outboxEvent.setEventType("TicketCreated");
        outboxEvent.setPayload(buildPayload(saved));
        outboxEventRepository.save(outboxEvent);

        return toResponse(saved);
    }

    private String buildPayload(Ticket ticket) {
        try {
            return objectMapper.writeValueAsString(Map.of(
                    "ticketId", ticket.getId().toString(),
                    "title", ticket.getTitle(),
                    "description", ticket.getDescription(),
                    "customerMetadata", ticket.getCustomerMetadata(),
                    "channel", ticket.getChannel().name(),
                    "correlationId", ticket.getCorrelationId().toString(),
                    "createdAt", ticket.getCreatedAt().toString()
            ));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize outbox payload", e);
        }
    }

    private TicketResponse toResponse(Ticket ticket) {
        return new TicketResponse(
                ticket.getId(),
                ticket.getTitle(),
                ticket.getDescription(),
                ticket.getCustomerMetadata(),
                ticket.getChannel(),
                ticket.getStatus(),
                ticket.getCreatedAt(),
                ticket.getUpdatedAt()
        );
    }
}
