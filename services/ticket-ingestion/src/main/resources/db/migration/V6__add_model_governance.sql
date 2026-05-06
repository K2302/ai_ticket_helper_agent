-- Phase 4: model governance — monitoring samples, threshold config, replay tracking

-- Online monitoring: per-reviewed-sample precision/recall proxy
create table model_monitor_samples (
    id                uuid        primary key default gen_random_uuid(),
    risk_decision_id  uuid        not null references risk_decisions(id),
    model_registry_id uuid        not null references model_registry(id),
    predicted_decision varchar(40) not null,
    actual_outcome     varchar(40),           -- filled in after human review/feedback
    score              numeric(5, 4) not null,
    score_delta        numeric(5, 4),          -- vs previous primary model
    is_drift_flagged   boolean not null default false,
    segment            varchar(120),           -- e.g. channel:WEB|tier:PREMIUM
    sampled_at         timestamptz not null default now(),
    constraint monitor_predicted_check check (
        predicted_decision in ('APPROVE', 'REVIEW', 'BLOCK')
    ),
    constraint monitor_actual_check check (
        actual_outcome is null or actual_outcome in ('APPROVE', 'REVIEW', 'BLOCK', 'CONFIRMED_FRAUD', 'NOT_FRAUD')
    )
);

create index idx_monitor_samples_model on model_monitor_samples (model_registry_id, sampled_at desc);
create index idx_monitor_samples_drift on model_monitor_samples (is_drift_flagged, sampled_at desc);

-- Per-segment threshold configuration
create table threshold_config (
    id          uuid        primary key default gen_random_uuid(),
    segment_key varchar(200) not null unique,  -- e.g. 'channel:WEB', 'tier:PREMIUM', 'default'
    block_threshold   numeric(4, 3) not null default 0.800,
    review_threshold  numeric(4, 3) not null default 0.500,
    approve_threshold numeric(4, 3) not null default 0.200,
    enabled     boolean not null default true,
    updated_at  timestamptz not null default now(),
    constraint threshold_order_check check (
        approve_threshold <= review_threshold and review_threshold <= block_threshold
    )
);

-- Insert default segment
insert into threshold_config (segment_key, block_threshold, review_threshold, approve_threshold)
values ('default', 0.800, 0.500, 0.200);

-- Kill switch: per-provider on/off control
create table model_kill_switch (
    id           uuid        primary key default gen_random_uuid(),
    provider_key varchar(200) not null unique,  -- e.g. 'openrouter:openai/gpt-4o-mini'
    active       boolean not null default false, -- true = kill switch ON (provider disabled)
    reason       text,
    activated_by varchar(200),
    activated_at timestamptz,
    deactivated_at timestamptz,
    updated_at   timestamptz not null default now()
);

-- Replay runs: tracks backtest jobs comparing model versions
create table replay_runs (
    id                uuid        primary key default gen_random_uuid(),
    challenger_model_id uuid      not null references model_registry(id),
    baseline_model_id   uuid      references model_registry(id),
    status            varchar(40) not null default 'PENDING',
    event_window_start timestamptz not null,
    event_window_end   timestamptz not null,
    total_events       int,
    processed_events   int not null default 0,
    result_summary     jsonb not null default '{}'::jsonb,
    started_at         timestamptz,
    completed_at       timestamptz,
    created_at         timestamptz not null default now(),
    constraint replay_status_check check (
        status in ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')
    )
);

create index idx_replay_runs_status on replay_runs (status, created_at desc);

-- Replay decision samples generated during a backtest
create table replay_decisions (
    id               uuid        primary key default gen_random_uuid(),
    replay_run_id    uuid        not null references replay_runs(id) on delete cascade,
    ticket_id        uuid        references tickets(id),
    original_decision varchar(40),
    replay_decision   varchar(40) not null,
    score_delta       numeric(5, 4),
    created_at        timestamptz not null default now(),
    constraint replay_decision_check check (replay_decision in ('APPROVE', 'REVIEW', 'BLOCK'))
);

create index idx_replay_decisions_run on replay_decisions (replay_run_id, created_at);
