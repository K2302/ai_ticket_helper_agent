create extension if not exists pgcrypto;

create table tickets (
    id               uuid         primary key default gen_random_uuid(),
    title            varchar(200) not null,
    description      text         not null,
    customer_metadata jsonb       not null default '{}'::jsonb,
    channel          varchar(40)  not null,
    status           varchar(40)  not null default 'RECEIVED',
    idempotency_key  varchar(200),
    correlation_id   uuid         not null default gen_random_uuid(),
    deleted_at       timestamptz,
    created_at       timestamptz  not null default now(),
    updated_at       timestamptz  not null default now(),
    constraint tickets_channel_check check (channel in ('EMAIL', 'CHAT', 'WEB', 'PHONE')),
    constraint tickets_status_check check (
        status in ('RECEIVED', 'TRIAGED', 'IN_REVIEW', 'RESOLVED', 'CLOSED', 'ARCHIVED')
    )
);

create index idx_tickets_status_created_at on tickets (status, created_at);
create unique index idx_tickets_idempotency_key on tickets (idempotency_key)
    where idempotency_key is not null;

-- Transactional outbox: written in same DB transaction as ticket insert
create table outbox_events (
    id             uuid         primary key default gen_random_uuid(),
    aggregate_id   uuid         not null,
    aggregate_type varchar(80)  not null,
    event_type     varchar(120) not null,
    payload        jsonb        not null,
    created_at     timestamptz  not null default now(),
    published_at   timestamptz,
    attempts       int          not null default 0,
    last_error     text,
    status         varchar(40)  not null default 'PENDING',
    constraint outbox_status_check check (status in ('PENDING', 'PUBLISHED', 'DLQ'))
);

create index idx_outbox_pending on outbox_events (created_at) where status = 'PENDING';
create index idx_outbox_aggregate on outbox_events (aggregate_id, aggregate_type);

-- Consumer-side deduplication
create table processed_events (
    idempotency_key varchar(200) not null,
    consumer_group  varchar(200) not null,
    processed_at    timestamptz  not null default now(),
    constraint processed_events_pk primary key (idempotency_key, consumer_group)
);

create index idx_processed_events_at on processed_events (processed_at desc);
