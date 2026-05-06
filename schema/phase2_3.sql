create table triage_results (
    id                  uuid        primary key default gen_random_uuid(),
    ticket_id           uuid        not null references tickets(id),
    correlation_id      uuid,
    category            varchar(80)  not null,
    priority            varchar(40)  not null,
    escalation_risk     varchar(40)  not null,
    assigned_team       varchar(80)  not null,
    confidence          numeric(4, 2) not null,
    requires_human_review boolean   not null default false,
    model_version       varchar(40)  not null,
    created_at          timestamptz  not null default now(),
    constraint triage_results_ticket_id_unique unique (ticket_id),
    constraint triage_results_priority_check check (priority in ('Low', 'Medium', 'High', 'Urgent')),
    constraint triage_results_escalation_risk_check check (escalation_risk in ('Low', 'Medium', 'High')),
    constraint triage_results_confidence_check check (confidence >= 0 and confidence <= 1)
);

create index idx_triage_results_requires_review on triage_results (requires_human_review, created_at);

-- Model registry: tracks model versions and lifecycle state
create table model_registry (
    id           uuid         primary key default gen_random_uuid(),
    name         varchar(200) not null,
    version      varchar(80)  not null,
    provider     varchar(120) not null,
    stage        varchar(40)  not null default 'CANDIDATE',
    config       jsonb        not null default '{}'::jsonb,
    promoted_at  timestamptz,
    retired_at   timestamptz,
    created_at   timestamptz  not null default now(),
    constraint model_registry_stage_check check (
        stage in ('CANDIDATE', 'SHADOW', 'CANARY', 'PRIMARY', 'RETIRED')
    ),
    constraint model_registry_name_version_unique unique (name, version)
);

create index idx_model_registry_stage on model_registry (stage, created_at desc);

-- Risk decisions: APPROVE / REVIEW / BLOCK with full explainability
create table risk_decisions (
    id                    uuid         primary key default gen_random_uuid(),
    ticket_id             uuid         not null references tickets(id),
    triage_result_id      uuid         references triage_results(id),
    correlation_id        uuid         not null,
    model_registry_id     uuid         references model_registry(id),
    decision              varchar(40)  not null,
    reason_code           varchar(120) not null,
    score                 numeric(5, 4) not null,
    policy_override       boolean      not null default false,
    policy_rule           varchar(200),
    feature_snapshot      jsonb        not null default '{}'::jsonb,
    feature_snapshot_hash varchar(64),
    explainability        jsonb        not null default '{}'::jsonb,
    model_version         varchar(120) not null,
    -- Phase 0: decision contract version fields for audit/replay
    rule_version          varchar(80)  not null default 'rules-v1',
    prompt_version        varchar(80),
    created_at            timestamptz  not null default now(),
    constraint risk_decision_check check (decision in ('APPROVE', 'REVIEW', 'BLOCK')),
    constraint risk_decisions_score_check check (score >= 0 and score <= 1)
);

create index idx_risk_decisions_ticket on risk_decisions (ticket_id, created_at desc);
create index idx_risk_decisions_decision on risk_decisions (decision, created_at desc);
create index idx_risk_decisions_correlation on risk_decisions (correlation_id);

create table human_review_queue (
    review_id        uuid        primary key default gen_random_uuid(),
    ticket_id        uuid        not null references tickets(id),
    triage_result_id uuid        not null references triage_results(id),
    risk_decision_id uuid        references risk_decisions(id),
    status           varchar(40) not null default 'PENDING',
    reason           varchar(80) not null,
    triage_snapshot  jsonb       not null,
    corrected_category     varchar(80),
    corrected_priority     varchar(40),
    corrected_team         varchar(80),
    corrected_escalation_risk varchar(40),
    reviewer         varchar(200),
    reviewed_at      timestamptz,
    deleted_at       timestamptz,
    created_at       timestamptz not null default now(),
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
