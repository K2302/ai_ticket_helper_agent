create extension if not exists pgcrypto;

create table tickets (
    id uuid primary key default gen_random_uuid(),
    title varchar(200) not null,
    description text not null,
    customer_metadata jsonb not null default '{}'::jsonb,
    channel varchar(40) not null,
    status varchar(40) not null default 'RECEIVED',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint tickets_channel_check check (channel in ('EMAIL', 'CHAT', 'WEB', 'PHONE')),
    constraint tickets_status_check check (status in ('RECEIVED'))
);

create index idx_tickets_status_created_at on tickets (status, created_at);
