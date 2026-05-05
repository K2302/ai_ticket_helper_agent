# AI Human Loop

## Phase 1

Backend-only ticket ingestion service.

### Folder Structure

```text
services/ticket-ingestion
  pom.xml
  src/main/java/com/aihumanloop/ingestion
    TicketIngestionApplication.java
    domain
    dto
    events
    repository
    service
    web
  src/main/resources
    application.yml
    db/migration/V1__create_tickets.sql
schema/phase1.sql
```

### Schema

See `schema/phase1.sql`.

### API

`POST /tickets`

```json
{
  "title": "Cannot access billing page",
  "description": "Customer gets a 500 error when opening billing.",
  "customerMetadata": {"customerId": "cus_123", "plan": "pro"},
  "channel": "EMAIL"
}
```

Publishes Kafka event to `support.ticket.created`.

### Config

```bash
DB_URL=jdbc:postgresql://localhost:5432/ai_human_loop
DB_USERNAME=postgres
DB_PASSWORD=postgres
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

### Run

```bash
cd services/ticket-ingestion
mvn spring-boot:run
```

## Run Locally

Requires:

- PostgreSQL
- ZooKeeper
- Kafka
- Java 21
- Maven

### 1. Start PostgreSQL

```bash
sudo systemctl start postgresql
sudo systemctl status postgresql
```

Create database:

```bash
sudo -u postgres psql -c "CREATE DATABASE ai_human_loop;"
```

Set local password:

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
ALTER USER postgres PASSWORD 'postgres';
\q
```

Connection string:

```text
postgresql://postgres:postgres@localhost:5432/ai_human_loop
```

### 2. Start ZooKeeper

Terminal 1:

```bash
cd ~/kafka_2.13-3.9.0/bin
./zookeeper-server-start.sh ../config/zookeeper.properties
```

Leave it running.

ZooKeeper runs on `localhost:2181`.

### 3. Start Kafka

Terminal 2:

```bash
cd ~/kafka_2.13-3.9.0/bin
./kafka-server-start.sh ../config/server.properties
```

Leave it running.

Kafka runs on `localhost:9092`.

### 4. Verify Kafka

Terminal 3:

```bash
lsof -i :9092
```

Optional topic check:

```bash
cd ~/kafka_2.13-3.9.0/bin
./kafka-topics.sh --bootstrap-server localhost:9092 --list
```

### 5. Start Spring Boot

Terminal 4:

```bash
cd ~/Proj/ai-human-loop/services/ticket-ingestion
mvn spring-boot:run
```

Expected:

- Spring Boot starts on `localhost:8080`
- connects to PostgreSQL
- Flyway creates schema
- connects to Kafka
- no Kafka connection retry spam

### 6. Test Ticket Ingestion

```bash
curl -X POST http://localhost:8080/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Login issue",
    "description": "Unable to login after password reset",
    "customerMetadata": {"customerId": "cust_001"},
    "channel": "WEB"
  }'
```

Expected:

- request accepted
- ticket saved
- event published to Kafka

### 7. Stop Everything

Stop in this order:

1. Spring Boot: `Ctrl+C`
2. Kafka: `Ctrl+C`
3. ZooKeeper: `Ctrl+C`

PostgreSQL can remain running.

### Ports

- PostgreSQL: `5432`
- ZooKeeper: `2181`
- Kafka: `9092`
- Spring Boot: `8080`

### Common Failures

PostgreSQL auth fails:

```bash
sudo -u postgres psql
```

Kafka says `Connection refused localhost:2181`:

- ZooKeeper is not running.
- Start ZooKeeper first.

Spring logs `Node -1 disconnected`:

- Kafka is not running.
- Start Kafka first.

## Phase 2 + 3

Backend-only AI triage service.

### Folder Structure

```text
services/ai-triage
  requirements.txt
  app
    main.py
    core/config.py
    domain/models.py
    schemas/dto.py
    infrastructure
      db.py
      kafka_consumer.py
      repositories.py
    services
      classifier.py
      priority.py
      escalation.py
      confidence.py
      routing.py
      triage_service.py
      human_review_service.py
schema/phase2_3.sql
```

### Schema

```bash
psql postgresql://postgres:postgres@localhost:5432/ai_human_loop -f schema/phase2_3.sql
```

Creates:

- `triage_results`
- `human_review_queue`

### Implementation

- Kafka consumer reads `support.ticket.created`
- Uses OpenRouter LLM for category, priority, escalation risk, and confidence when `OPENROUTER_API_KEY` is set
- Falls back to local rules when OpenRouter is not configured or the request fails
- Computes confidence
- Routes to team with rules only
- Enqueues low-confidence or high-risk tickets for human review
- Allows review decisions and applies override to `triage_results`

### Config

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_human_loop
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
TICKET_CREATED_TOPIC=support.ticket.created
KAFKA_GROUP_ID=ai-triage-service
LOW_CONFIDENCE_THRESHOLD=0.70
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_APP_TITLE=ai-human-loop
```

### Run

```bash
cd services/ai-triage
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Enable OpenRouter

```bash
export OPENROUTER_API_KEY=your_key
export OPENROUTER_MODEL=openai/gpt-4o-mini
```

Without `OPENROUTER_API_KEY`, triage uses `rules-v1`.
With `OPENROUTER_API_KEY`, `triage_results.model_version` is `openrouter:<model>`.

### APIs

```bash
curl http://127.0.0.1:8000/triage-results/{ticket_id}
curl http://127.0.0.1:8000/reviews/pending
```

```bash
curl -X POST http://127.0.0.1:8000/reviews/{review_id}/decision \
  -H 'Content-Type: application/json' \
  -d '{
    "reviewer": "ops@example.com",
    "corrected_category": "Technical Support",
    "corrected_priority": "High",
    "corrected_team": "Technical Support",
    "corrected_escalation_risk": "Medium"
  }'
```

### Verify Triage Pipeline

Preconditions:

- PostgreSQL is running
- ZooKeeper is running
- Kafka is running
- Spring ticket-ingestion is running
- FastAPI ai-triage is running
- `schema/phase2_3.sql` has been applied

Open PostgreSQL:

```bash
psql postgresql://postgres:postgres@localhost:5432/ai_human_loop
```

Check inserted tickets:

```sql
select id, title, created_at
from tickets
order by created_at desc
limit 5;
```

Expected: at least one ticket row.

Check triage result for one ticket:

```sql
select *
from triage_results
where ticket_id = 'replace-with-ticket-uuid';
```

Expected if processed:

- `ticket_id`
- `category`
- `priority`
- `escalation_risk`
- `assigned_team`
- `confidence`
- `requires_human_review`
- `model_version`

Check whether any triage results exist:

```sql
select ticket_id, category, confidence, requires_human_review
from triage_results
order by created_at desc
limit 10;
```

If rows exist, the pipeline works. If empty, the AI triage worker has not written results.

Check pending human reviews:

```bash
curl http://127.0.0.1:8000/reviews/pending
```

Expected:

- `[]`: no tickets currently need review
- rows returned: triage pipeline is working and flagged tickets for review

Check triage result API:

```bash
curl http://127.0.0.1:8000/triage-results/<ticket_id>
```

Expected if processed:

```json
{
  "ticket_id": "...",
  "category": "Billing",
  "priority": "Medium",
  "escalation_risk": "Low",
  "assigned_team": "Billing Support",
  "confidence": 0.74,
  "requires_human_review": false
}
```

If response is:

```json
{"detail":"Triage result not found"}
```

The ticket exists, but no triage result was written.

Fast state check:

```sql
select count(*) from tickets;
select count(*) from triage_results;
select count(*) from human_review_queue where status = 'PENDING';
```

Healthy state:

- `tickets > 0`
- `triage_results > 0`
- `human_review_queue >= 0`

Fault boundary:

- `tickets > 0` and `triage_results = 0`: ingestion works, AI triage processing is broken
- likely causes: consumer not running, wrong topic/group config, message not consumed, classification error, insert failure

## Phase 4

Feedback capture and audit logging.

### Schema

```bash
psql postgresql://postgres:postgres@localhost:5432/ai_human_loop -f schema/phase4.sql
```

Creates:

- `feedback_corrections`
- `audit_logs`

Spring Flyway also includes:

- `V3__create_feedback_and_audit_tables.sql`

### Implementation

- Human review decisions create feedback correction rows
- Manual feedback can be submitted for any ticket with an existing triage result
- Triage completion writes an audit log
- Human review resolution writes an audit log
- Feedback capture writes an audit log

### APIs

Submit feedback:

```bash
curl -X POST http://127.0.0.1:8000/tickets/{ticket_id}/feedback \
  -H 'Content-Type: application/json' \
  -d '{
    "reviewer": "ops@example.com",
    "corrected_category": "Technical Support",
    "corrected_priority": "High",
    "corrected_team": "Technical Support",
    "corrected_escalation_risk": "Medium",
    "notes": "Corrected after manual inspection"
  }'
```

List feedback:

```bash
curl http://127.0.0.1:8000/tickets/{ticket_id}/feedback
```

List audit logs:

```bash
curl http://127.0.0.1:8000/tickets/{ticket_id}/audit-logs
```

### Verify

```sql
select count(*) from feedback_corrections;
select count(*) from audit_logs;
select ticket_id, action, actor, created_at
from audit_logs
order by created_at desc
limit 10;
```

Kafka starts but Spring still fails:

```bash
lsof -i :9092
```

If nothing is listening, Kafka is not actually up.

Could not connect to `archive.ubuntu.com`:

```bash
sudo apt -o Acquire::ForceIPv4=true update
```
