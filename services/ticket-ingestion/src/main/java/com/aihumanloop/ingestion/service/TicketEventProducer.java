package com.aihumanloop.ingestion.service;

import com.aihumanloop.ingestion.events.TicketCreatedEvent;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class TicketEventProducer {
    private final KafkaTemplate<String, TicketCreatedEvent> kafkaTemplate;
    private final String ticketCreatedTopic;

    public TicketEventProducer(
            KafkaTemplate<String, TicketCreatedEvent> kafkaTemplate,
            @Value("${app.kafka.topics.ticket-created}") String ticketCreatedTopic
    ) {
        this.kafkaTemplate = kafkaTemplate;
        this.ticketCreatedTopic = ticketCreatedTopic;
    }

    public void publish(TicketCreatedEvent event) {
        kafkaTemplate.send(ticketCreatedTopic, event.ticketId().toString(), event).join();
    }
}
