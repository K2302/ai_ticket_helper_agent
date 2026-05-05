# AI Triage Service

Phase 2 + 3 service: Kafka consumer, OpenRouter LLM triage with rules fallback, confidence scoring, rule routing, human review queue.

## Apply Schema

```bash
psql postgresql://postgres:postgres@localhost:5432/ai_human_loop -f ../../schema/phase2_3.sql
```

## Run

```bash
cd services/ai-triage
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Config

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

OpenRouter is optional. If `OPENROUTER_API_KEY` is missing or the request fails, the service falls back to `rules-v1`.

## APIs

```bash
curl http://127.0.0.1:8000/triage-results/{ticket_id}
curl http://127.0.0.1:8000/reviews/pending
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

## Phase 4 APIs

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

```bash
curl http://127.0.0.1:8000/tickets/{ticket_id}/feedback
curl http://127.0.0.1:8000/tickets/{ticket_id}/audit-logs
```
