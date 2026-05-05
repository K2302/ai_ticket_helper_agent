# Ticket Ingestion Service

Phase 1 service: REST ticket ingestion, PostgreSQL persistence, Kafka `support.ticket.created` producer.

## Run

```bash
cd services/ticket-ingestion
export DB_URL=jdbc:postgresql://localhost:5432/ai_human_loop
export DB_USERNAME=postgres
export DB_PASSWORD=postgres
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
mvn spring-boot:run
```

## Create Ticket

```bash
curl -X POST http://localhost:8080/tickets \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Cannot access billing page",
    "description": "Customer gets a 500 error when opening billing.",
    "customerMetadata": {"customerId": "cus_123", "plan": "pro"},
    "channel": "EMAIL"
  }'
```
