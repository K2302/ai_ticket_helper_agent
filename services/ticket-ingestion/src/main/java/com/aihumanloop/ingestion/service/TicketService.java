package com.aihumanloop.ingestion.service;

import com.aihumanloop.ingestion.domain.Ticket;
import com.aihumanloop.ingestion.dto.CreateTicketRequest;
import com.aihumanloop.ingestion.dto.TicketResponse;
import com.aihumanloop.ingestion.events.TicketCreatedEvent;
import com.aihumanloop.ingestion.repository.TicketRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketService {
    private final TicketRepository ticketRepository;
    private final TicketEventProducer eventProducer;

    public TicketService(
            TicketRepository ticketRepository,
            TicketEventProducer eventProducer
    ) {
        this.ticketRepository = ticketRepository;
        this.eventProducer = eventProducer;
    }

    @Transactional
    public TicketResponse create(CreateTicketRequest request) {
        Ticket ticket = new Ticket();
        ticket.setTitle(request.title());
        ticket.setDescription(request.description());
        ticket.setCustomerMetadata(request.customerMetadata());
        ticket.setChannel(request.channel());

        Ticket saved = ticketRepository.saveAndFlush(ticket);
        TicketResponse response = toResponse(saved);
        eventProducer.publish(new TicketCreatedEvent(
                saved.getId(),
                saved.getTitle(),
                saved.getDescription(),
                saved.getCustomerMetadata(),
                saved.getChannel(),
                saved.getCreatedAt()
        ));
        return response;
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
