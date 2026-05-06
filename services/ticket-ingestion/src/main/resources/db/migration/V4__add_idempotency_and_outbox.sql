-- Phase 1: idempotency keys, correlation ids, soft-delete, outbox, processed-events

-- Add idempotency_key and correlation_id to tickets; remove hard status constraint for future statuses
alter table tickets
    add column idempotency_key varchar(200),
    add column correlation_id  uuid not null default gen_random_uuid(),
    add column deleted_at      timestamptz;

create unique index idx_tickets_idempotency_key on tickets (idempotency_key)
    where idempotency_key is not null;

-- Broaden status check to cover downstream lifecycle statuses
alter table tickets
    drop constraint tickets_status_check,
    add constraint tickets_status_check check (
        status in ('RECEIVED', 'TRIAGED', 'IN_REVIEW', 'RESOLVED', 'CLOSED', 'ARCHIVED')
    );

-- Add correlation_id to triage_results
alter table triage_results
    add column correlation_id uuid;

-- Add correlation_id to audit_logs
alter table audit_logs
    add column correlation_id uuid;

-- Transactional outbox: Java service writes here in same TX as ticket insert
create table outbox_events (
    id            uuid        primary key default gen_random_uuid(),
    aggregate_id  uuid        not null,
    aggregate_type varchar(80) not null,
    event_type    varchar(120) not null,
    payload       jsonb       not null,
    created_at    timestamptz not null default now(),
    published_at  timestamptz,
    attempts      int         not null default 0,
    last_error    text,
    status        varchar(40) not null default 'PENDING',
    constraint outbox_status_check check (status in ('PENDING', 'PUBLISHED', 'DLQ'))
);

create index idx_outbox_pending on outbox_events (created_at) where status = 'PENDING';
create index idx_outbox_aggregate on outbox_events (aggregate_id, aggregate_type);

-- Consumer-side deduplication: Python consumer records processed idempotency keys here
create table processed_events (
    idempotency_key varchar(200) not null,
    consumer_group  varchar(200) not null,
    processed_at    timestamptz  not null default now(),
    constraint processed_events_pk primary key (idempotency_key, consumer_group)
);

create index idx_processed_events_at on processed_events (processed_at desc);
