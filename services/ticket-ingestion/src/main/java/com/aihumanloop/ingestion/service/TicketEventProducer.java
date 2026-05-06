package com.aihumanloop.ingestion.service;

import com.aihumanloop.ingestion.domain.OutboxEvent;
import com.aihumanloop.ingestion.repository.OutboxEventRepository;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Outbox relay publisher. Polls PENDING outbox rows, publishes to Kafka, then
 * marks each row PUBLISHED or DLQ depending on success/failure. Runs on a
 * fixed-rate schedule so the main request path never blocks on Kafka.
 */
@Component
public class TicketEventProducer {
    private static final Logger log = LoggerFactory.getLogger(TicketEventProducer.class);
    private static final int BATCH_SIZE = 50;
    private static final int MAX_ATTEMPTS_BEFORE_DLQ = 5;

    private final KafkaTemplate<String, String> kafkaTemplate;
    private final OutboxEventRepository outboxEventRepository;
    private final String ticketCreatedTopic;
    private final String ticketDlqTopic;

    public TicketEventProducer(
            KafkaTemplate<String, String> kafkaTemplate,
            OutboxEventRepository outboxEventRepository,
            @Value("${app.kafka.topics.ticket-created}") String ticketCreatedTopic,
            @Value("${app.kafka.topics.ticket-dlq}") String ticketDlqTopic
    ) {
        this.kafkaTemplate = kafkaTemplate;
        this.outboxEventRepository = outboxEventRepository;
        this.ticketCreatedTopic = ticketCreatedTopic;
        this.ticketDlqTopic = ticketDlqTopic;
    }

    @Scheduled(fixedDelayString = "${app.outbox.relay-interval-ms:500}")
    @Transactional
    public void relay() {
        List<OutboxEvent> pending = outboxEventRepository.fetchPendingForUpdate(BATCH_SIZE);
        for (OutboxEvent event : pending) {
            String targetTopic = event.getAttempts() >= MAX_ATTEMPTS_BEFORE_DLQ
                    ? ticketDlqTopic
                    : ticketCreatedTopic;
            try {
                kafkaTemplate
                        .send(targetTopic, event.getAggregateId().toString(), event.getPayload())
                        .get(); // block until ack — producer acks = all is set in application.yml
                outboxEventRepository.markProcessed(
                        event.getId(),
                        targetTopic.equals(ticketDlqTopic)
                                ? OutboxEvent.Status.DLQ.name()
                                : OutboxEvent.Status.PUBLISHED.name(),
                        null
                );
            } catch (Exception ex) {
                log.warn("Outbox relay failed for event={} attempt={}: {}",
                        event.getId(), event.getAttempts() + 1, ex.getMessage());
                outboxEventRepository.markProcessed(
                        event.getId(),
                        OutboxEvent.Status.PENDING.name(),
                        ex.getMessage()
                );
            }
        }
    }
}
