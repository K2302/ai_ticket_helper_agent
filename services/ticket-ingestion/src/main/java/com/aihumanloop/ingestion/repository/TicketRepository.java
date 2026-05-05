package com.aihumanloop.ingestion.repository;

import com.aihumanloop.ingestion.domain.Ticket;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TicketRepository extends JpaRepository<Ticket, UUID> {
}
