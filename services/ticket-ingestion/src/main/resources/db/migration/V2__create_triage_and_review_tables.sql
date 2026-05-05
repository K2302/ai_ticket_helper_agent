create table triage_results (
    id uuid primary key default gen_random_uuid(),
    ticket_id uuid not null references tickets(id) on delete cascade,
    category varchar(80) not null,
    priority varchar(40) not null,
    escalation_risk varchar(40) not null,
    assigned_team varchar(80) not null,
    confidence numeric(4, 2) not null,
    requires_human_review boolean not null default false,
    model_version varchar(40) not null,
    created_at timestamptz not null default now(),
    constraint triage_results_ticket_id_unique unique (ticket_id),
    constraint triage_results_priority_check check (priority in ('Low', 'Medium', 'High', 'Urgent')),
    constraint triage_results_escalation_risk_check check (escalation_risk in ('Low', 'Medium', 'High')),
    constraint triage_results_confidence_check check (confidence >= 0 and confidence <= 1)
);

create index idx_triage_results_requires_review on triage_results (requires_human_review, created_at);

create table human_review_queue (
    review_id uuid primary key default gen_random_uuid(),
    ticket_id uuid not null references tickets(id) on delete cascade,
    triage_result_id uuid not null references triage_results(id) on delete cascade,
    status varchar(40) not null default 'PENDING',
    reason varchar(80) not null,
    triage_snapshot jsonb not null,
    corrected_category varchar(80),
    corrected_priority varchar(40),
    corrected_team varchar(80),
    corrected_escalation_risk varchar(40),
    reviewer varchar(200),
    reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    constraint human_review_status_check check (status in ('PENDING', 'RESOLVED')),
    constraint human_review_corrected_priority_check check (
        corrected_priority is null or corrected_priority in ('Low', 'Medium', 'High', 'Urgent')
    ),
    constraint human_review_corrected_escalation_risk_check check (
        corrected_escalation_risk is null or corrected_escalation_risk in ('Low', 'Medium', 'High')
    )
);

create unique index idx_human_review_one_pending_per_ticket
    on human_review_queue (ticket_id)
    where status = 'PENDING';

create index idx_human_review_pending_created_at
    on human_review_queue (status, created_at);
