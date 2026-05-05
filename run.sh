#!/usr/bin/env bash
set -euo pipefail

DB_NAME="ai_human_loop"
DB_USER="postgres"
DB_PASSWORD="postgres"
DB_HOST="localhost"
DB_PORT="5432"

PROJECT_ROOT="$HOME/Proj/ai-human-loop"
INGESTION_DIR="$PROJECT_ROOT/services/ticket-ingestion"
TICKET_TOPIC="support.ticket.created"

export PGPASSWORD="$DB_PASSWORD"

echo "==> Stopping old app processes"
pkill -f 'ticket-ingestion' || true
pkill -f 'spring-boot:run' || true

echo "==> Terminating active DB sessions"
psql "postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/postgres" -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$DB_NAME'
  AND pid <> pg_backend_pid();
" >/dev/null

echo "==> Resetting database: $DB_NAME"
dropdb   -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists "$DB_NAME"
createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"

echo "==> Verifying PostgreSQL"
psql "postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME" -c "select version();"

echo "==> Starting Kafka"
docker start zookeeper >/dev/null 2>&1 || true
docker start kafka >/dev/null 2>&1 || true

echo "==> Waiting for Kafka"
sleep 5

echo "==> Resetting Kafka topic: $TICKET_TOPIC"
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --delete \
  --if-exists \
  --topic "$TICKET_TOPIC" >/dev/null 2>&1 || true
for _ in {1..10}; do
  if ! docker exec kafka /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --describe \
    --topic "$TICKET_TOPIC" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Starting Spring Boot ingestion service"
cd "$INGESTION_DIR"
exec mvn spring-boot:run
