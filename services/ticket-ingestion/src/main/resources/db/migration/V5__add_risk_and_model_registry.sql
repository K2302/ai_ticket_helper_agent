-- Phase 3: model registry and risk decisions

-- Model registry: tracks model versions and lifecycle state
create table model_registry (
    id              uuid        primary key default gen_random_uuid(),
    name            varchar(200) not null,
    version         varchar(80)  not null,
    provider        varchar(120) not null,  -- e.g. 'openrouter:openai/gpt-4o-mini', 'rules-v1'
    stage           varchar(40)  not null default 'CANDIDATE',
    config          jsonb        not null default '{}'::jsonb,
    promoted_at     timestamptz,
    retired_at      timestamptz,
    created_at      timestamptz  not null default now(),
    constraint model_registry_stage_check check (
        stage in ('CANDIDATE', 'SHADOW', 'CANARY', 'PRIMARY', 'RETIRED')
    ),
    constraint model_registry_name_version_unique unique (name, version)
);

create index idx_model_registry_stage on model_registry (stage, created_at desc);

-- Risk decisions: full decision record with APPROVE/REVIEW/BLOCK + explainability
create table risk_decisions (
    id                   uuid        primary key default gen_random_uuid(),
    ticket_id            uuid        not null references tickets(id),
    triage_result_id     uuid        references triage_results(id),
    correlation_id       uuid        not null,
    model_registry_id    uuid        references model_registry(id),
    decision             varchar(40)  not null,
    reason_code          varchar(120) not null,
    score                numeric(5, 4) not null,
    policy_override      boolean      not null default false,
    policy_rule          varchar(200),
    feature_snapshot     jsonb        not null default '{}'::jsonb,
    feature_snapshot_hash varchar(64),
    explainability       jsonb        not null default '{}'::jsonb,
    model_version        varchar(120) not null,
    created_at           timestamptz  not null default now(),
    constraint risk_decision_check check (decision in ('APPROVE', 'REVIEW', 'BLOCK')),
    constraint risk_decisions_score_check check (score >= 0 and score <= 1)
);

create index idx_risk_decisions_ticket on risk_decisions (ticket_id, created_at desc);
create index idx_risk_decisions_decision on risk_decisions (decision, created_at desc);
create index idx_risk_decisions_correlation on risk_decisions (correlation_id);

-- Human review queue: add risk_decision_id linkage
alter table human_review_queue
    add column risk_decision_id uuid references risk_decisions(id),
    add column deleted_at       timestamptz;

-- feedback_corrections: add risk_decision_id linkage
alter table feedback_corrections
    add column risk_decision_id uuid references risk_decisions(id);

-- audit_logs: extend allowed action types for Phase 3
alter table audit_logs
    drop constraint audit_logs_action_check,
    add constraint audit_logs_action_check check (
        action in (
            'TRIAGE_COMPLETED', 'HUMAN_REVIEW_RESOLVED', 'FEEDBACK_CAPTURED',
            'RISK_DECISION_MADE', 'MODEL_PROMOTED', 'MODEL_RETIRED',
            'KILL_SWITCH_ACTIVATED', 'KILL_SWITCH_DEACTIVATED',
            'REPLAY_STARTED', 'REPLAY_COMPLETED'
        )
    );
