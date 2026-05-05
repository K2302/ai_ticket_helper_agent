create table feedback_corrections (
    feedback_id uuid primary key default gen_random_uuid(),
    ticket_id uuid not null references tickets(id) on delete cascade,
    triage_result_id uuid not null references triage_results(id) on delete cascade,
    review_id uuid references human_review_queue(review_id) on delete set null,
    original_prediction jsonb not null,
    corrected_prediction jsonb not null,
    reviewer varchar(200) not null,
    notes text,
    created_at timestamptz not null default now()
);

create index idx_feedback_corrections_ticket_created_at
    on feedback_corrections (ticket_id, created_at desc);

create table audit_logs (
    audit_id uuid primary key default gen_random_uuid(),
    ticket_id uuid references tickets(id) on delete set null,
    actor varchar(200) not null,
    action varchar(80) not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint audit_logs_action_check check (
        action in ('TRIAGE_COMPLETED', 'HUMAN_REVIEW_RESOLVED', 'FEEDBACK_CAPTURED')
    )
);

create index idx_audit_logs_ticket_created_at
    on audit_logs (ticket_id, created_at desc);

create index idx_audit_logs_action_created_at
    on audit_logs (action, created_at desc);
