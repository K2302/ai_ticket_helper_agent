package com.aihumanloop.ingestion.repository;

import com.aihumanloop.ingestion.domain.OutboxEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface OutboxEventRepository extends JpaRepository<OutboxEvent, UUID> {

    @Query(value = "SELECT * FROM outbox_events WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT :limit FOR UPDATE SKIP LOCKED", nativeQuery = true)
    List<OutboxEvent> fetchPendingForUpdate(@Param("limit") int limit);

    @Modifying
    @Query("UPDATE OutboxEvent o SET o.status = :status, o.lastError = :error, o.attempts = o.attempts + 1, o.publishedAt = CURRENT_TIMESTAMP WHERE o.id = :id")
    void markProcessed(@Param("id") UUID id, @Param("status") String status, @Param("error") String error);
}
