import json
from uuid import UUID

from app.domain.models import (
    AuditAction,
    AuditLog,
    Category,
    EscalationRisk,
    FeedbackCorrection,
    HumanReview,
    ModelKillSwitch,
    ModelRegistry,
    ModelStage,
    Priority,
    ReplayRun,
    ReplayStatus,
    ReviewStatus,
    RiskDecision,
    RiskDecisionOutcome,
    ThresholdConfig,
    TriageResult,
)
from app.infrastructure.db import Database


class TriageResultRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        assigned_team: str,
        confidence: float,
        requires_human_review: bool,
        model_version: str,
        correlation_id: UUID | None = None,
    ) -> TriageResult:
        row = await self.database.require_pool().fetchrow(
            """
            insert into triage_results (
                ticket_id, correlation_id, category, priority, escalation_risk,
                assigned_team, confidence, requires_human_review, model_version
            )
            values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            on conflict (ticket_id) do update set
                correlation_id = excluded.correlation_id,
                category = excluded.category,
                priority = excluded.priority,
                escalation_risk = excluded.escalation_risk,
                assigned_team = excluded.assigned_team,
                confidence = excluded.confidence,
                requires_human_review = excluded.requires_human_review,
                model_version = excluded.model_version
            returning *
            """,
            ticket_id,
            correlation_id,
            category.value,
            priority.value,
            escalation_risk.value,
            assigned_team,
            confidence,
            requires_human_review,
            model_version,
        )
        return self._to_domain(row)

    async def get_by_ticket_id(self, ticket_id: UUID) -> TriageResult | None:
        row = await self.database.require_pool().fetchrow(
            "select * from triage_results where ticket_id = $1",
            ticket_id,
        )
        return self._to_domain(row) if row else None

    async def get_by_id(self, result_id: UUID) -> TriageResult | None:
        row = await self.database.require_pool().fetchrow(
            "select * from triage_results where id = $1",
            result_id,
        )
        return self._to_domain(row) if row else None

    async def apply_override(
        self,
        result_id: UUID,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        assigned_team: str,
    ) -> None:
        await self.database.require_pool().execute(
            """
            update triage_results
            set category = $2,
                priority = $3,
                escalation_risk = $4,
                assigned_team = $5,
                requires_human_review = false
            where id = $1
            """,
            result_id,
            category.value,
            priority.value,
            escalation_risk.value,
            assigned_team,
        )

    def _to_domain(self, row) -> TriageResult:
        return TriageResult(
            id=row["id"],
            ticket_id=row["ticket_id"],
            category=Category(row["category"]),
            priority=Priority(row["priority"]),
            escalation_risk=EscalationRisk(row["escalation_risk"]),
            assigned_team=row["assigned_team"],
            confidence=float(row["confidence"]),
            requires_human_review=row["requires_human_review"],
            model_version=row["model_version"],
            created_at=row["created_at"],
            correlation_id=row.get("correlation_id"),
        )


class HumanReviewRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def enqueue(self, triage_result: TriageResult, reason: str, snapshot: dict, risk_decision_id: UUID | None = None) -> HumanReview:
        row = await self.database.require_pool().fetchrow(
            """
            insert into human_review_queue (
                ticket_id, triage_result_id, risk_decision_id, reason, triage_snapshot
            )
            values ($1, $2, $3, $4, $5::jsonb)
            on conflict (ticket_id) where status = 'PENDING' do update set
                triage_result_id = excluded.triage_result_id,
                risk_decision_id = excluded.risk_decision_id,
                reason = excluded.reason,
                triage_snapshot = excluded.triage_snapshot
            returning *
            """,
            triage_result.ticket_id,
            triage_result.id,
            risk_decision_id,
            reason,
            json.dumps(snapshot),
        )
        return self._to_domain(row)

    async def list_pending(self) -> list[HumanReview]:
        rows = await self.database.require_pool().fetch(
            """
            select * from human_review_queue
            where status = 'PENDING'
            order by created_at asc
            """
        )
        return [self._to_domain(row) for row in rows]

    async def resolve(
        self,
        review_id: UUID,
        reviewer: str,
        corrected_category: Category,
        corrected_priority: Priority,
        corrected_team: str,
        corrected_escalation_risk: EscalationRisk,
    ) -> HumanReview | None:
        row = await self.database.require_pool().fetchrow(
            """
            update human_review_queue
            set status = 'RESOLVED',
                reviewer = $2,
                corrected_category = $3,
                corrected_priority = $4,
                corrected_team = $5,
                corrected_escalation_risk = $6,
                reviewed_at = now()
            where review_id = $1 and status = 'PENDING'
            returning *
            """,
            review_id,
            reviewer,
            corrected_category.value,
            corrected_priority.value,
            corrected_team,
            corrected_escalation_risk.value,
        )
        return self._to_domain(row) if row else None

    def _to_domain(self, row) -> HumanReview:
        return HumanReview(
            review_id=row["review_id"],
            ticket_id=row["ticket_id"],
            triage_result_id=row["triage_result_id"],
            risk_decision_id=row.get("risk_decision_id"),
            status=ReviewStatus(row["status"]),
            reason=row["reason"],
            triage_snapshot=self._json_dict(row["triage_snapshot"]),
            corrected_category=row["corrected_category"],
            corrected_priority=row["corrected_priority"],
            corrected_team=row["corrected_team"],
            corrected_escalation_risk=row["corrected_escalation_risk"],
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class FeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID,
        triage_result_id: UUID,
        review_id: UUID | None,
        original_prediction: dict,
        corrected_prediction: dict,
        reviewer: str,
        notes: str | None,
    ) -> FeedbackCorrection:
        row = await self.database.require_pool().fetchrow(
            """
            insert into feedback_corrections (
                ticket_id, triage_result_id, review_id, original_prediction,
                corrected_prediction, reviewer, notes
            )
            values ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
            returning *
            """,
            ticket_id,
            triage_result_id,
            review_id,
            json.dumps(original_prediction),
            json.dumps(corrected_prediction),
            reviewer,
            notes,
        )
        return self._to_domain(row)

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[FeedbackCorrection]:
        rows = await self.database.require_pool().fetch(
            """
            select * from feedback_corrections
            where ticket_id = $1
            order by created_at desc
            """,
            ticket_id,
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> FeedbackCorrection:
        return FeedbackCorrection(
            feedback_id=row["feedback_id"],
            ticket_id=row["ticket_id"],
            triage_result_id=row["triage_result_id"],
            risk_decision_id=row.get("risk_decision_id"),
            review_id=row["review_id"],
            original_prediction=self._json_dict(row["original_prediction"]),
            corrected_prediction=self._json_dict(row["corrected_prediction"]),
            reviewer=row["reviewer"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class AuditLogRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID | None,
        actor: str,
        action: AuditAction,
        details: dict,
        correlation_id: UUID | None = None,
    ) -> AuditLog:
        row = await self.database.require_pool().fetchrow(
            """
            insert into audit_logs (ticket_id, correlation_id, actor, action, details)
            values ($1, $2, $3, $4, $5::jsonb)
            returning *
            """,
            ticket_id,
            correlation_id,
            actor,
            action.value,
            json.dumps(details),
        )
        return self._to_domain(row)

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[AuditLog]:
        rows = await self.database.require_pool().fetch(
            """
            select * from audit_logs
            where ticket_id = $1
            order by created_at desc
            """,
            ticket_id,
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> AuditLog:
        return AuditLog(
            audit_id=row["audit_id"],
            ticket_id=row["ticket_id"],
            correlation_id=row.get("correlation_id"),
            actor=row["actor"],
            action=AuditAction(row["action"]),
            details=self._json_dict(row["details"]),
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class ProcessedEventRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def is_processed(self, idempotency_key: str, consumer_group: str) -> bool:
        row = await self.database.require_pool().fetchrow(
            """
            select 1 from processed_events
            where idempotency_key = $1 and consumer_group = $2
            """,
            idempotency_key,
            consumer_group,
        )
        return row is not None

    async def mark_processed(self, idempotency_key: str, consumer_group: str) -> None:
        await self.database.require_pool().execute(
            """
            insert into processed_events (idempotency_key, consumer_group)
            values ($1, $2)
            on conflict do nothing
            """,
            idempotency_key,
            consumer_group,
        )


class RiskDecisionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        ticket_id: UUID,
        triage_result_id: UUID | None,
        correlation_id: UUID,
        model_registry_id: UUID | None,
        decision: RiskDecisionOutcome,
        reason_code: str,
        score: float,
        policy_override: bool,
        policy_rule: str | None,
        feature_snapshot: dict,
        feature_snapshot_hash: str | None,
        explainability: dict,
        model_version: str,
        rule_version: str = "rules-v1",
        prompt_version: str | None = None,
    ) -> RiskDecision:
        row = await self.database.require_pool().fetchrow(
            """
            insert into risk_decisions (
                ticket_id, triage_result_id, correlation_id, model_registry_id,
                decision, reason_code, score, policy_override, policy_rule,
                feature_snapshot, feature_snapshot_hash, explainability,
                model_version, rule_version, prompt_version
            ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12::jsonb,$13,$14,$15)
            returning *
            """,
            ticket_id, triage_result_id, correlation_id, model_registry_id,
            decision.value, reason_code, score, policy_override, policy_rule,
            json.dumps(feature_snapshot), feature_snapshot_hash,
            json.dumps(explainability), model_version, rule_version, prompt_version,
        )
        return self._to_domain(row)

    async def get_by_ticket_id(self, ticket_id: UUID) -> RiskDecision | None:
        row = await self.database.require_pool().fetchrow(
            "select * from risk_decisions where ticket_id = $1 order by created_at desc limit 1",
            ticket_id,
        )
        return self._to_domain(row) if row else None

    async def get_by_id(self, decision_id: UUID) -> RiskDecision | None:
        row = await self.database.require_pool().fetchrow(
            "select * from risk_decisions where id = $1",
            decision_id,
        )
        return self._to_domain(row) if row else None

    def _to_domain(self, row) -> RiskDecision:
        return RiskDecision(
            id=row["id"],
            ticket_id=row["ticket_id"],
            triage_result_id=row["triage_result_id"],
            correlation_id=row["correlation_id"],
            model_registry_id=row["model_registry_id"],
            decision=RiskDecisionOutcome(row["decision"]),
            reason_code=row["reason_code"],
            score=float(row["score"]),
            policy_override=row["policy_override"],
            policy_rule=row["policy_rule"],
            feature_snapshot=self._json_dict(row["feature_snapshot"]),
            feature_snapshot_hash=row["feature_snapshot_hash"],
            explainability=self._json_dict(row["explainability"]),
            model_version=row["model_version"],
            rule_version=row["rule_version"],
            prompt_version=row.get("prompt_version"),
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class ModelRegistryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_primary(self) -> ModelRegistry | None:
        row = await self.database.require_pool().fetchrow(
            "select * from model_registry where stage = 'PRIMARY' order by promoted_at desc limit 1"
        )
        return self._to_domain(row) if row else None

    async def get_by_stage(self, stage: ModelStage) -> list[ModelRegistry]:
        rows = await self.database.require_pool().fetch(
            "select * from model_registry where stage = $1 order by created_at desc",
            stage.value,
        )
        return [self._to_domain(row) for row in rows]

    async def get_by_id(self, model_id: UUID) -> ModelRegistry | None:
        row = await self.database.require_pool().fetchrow(
            "select * from model_registry where id = $1", model_id
        )
        return self._to_domain(row) if row else None

    async def create(
        self,
        name: str,
        version: str,
        provider: str,
        config: dict,
        stage: ModelStage = ModelStage.CANDIDATE,
    ) -> ModelRegistry:
        row = await self.database.require_pool().fetchrow(
            """
            insert into model_registry (name, version, provider, config, stage)
            values ($1, $2, $3, $4::jsonb, $5)
            returning *
            """,
            name, version, provider, json.dumps(config), stage.value,
        )
        return self._to_domain(row)

    async def promote(self, model_id: UUID, stage: ModelStage) -> ModelRegistry | None:
        row = await self.database.require_pool().fetchrow(
            """
            update model_registry
            set stage = $2,
                promoted_at = case when $2 = 'PRIMARY' then now() else promoted_at end
            where id = $1
            returning *
            """,
            model_id, stage.value,
        )
        return self._to_domain(row) if row else None

    async def retire(self, model_id: UUID) -> ModelRegistry | None:
        row = await self.database.require_pool().fetchrow(
            """
            update model_registry
            set stage = 'RETIRED', retired_at = now()
            where id = $1
            returning *
            """,
            model_id,
        )
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[ModelRegistry]:
        rows = await self.database.require_pool().fetch(
            "select * from model_registry order by created_at desc"
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> ModelRegistry:
        return ModelRegistry(
            id=row["id"],
            name=row["name"],
            version=row["version"],
            provider=row["provider"],
            stage=ModelStage(row["stage"]),
            config=self._json_dict(row["config"]),
            promoted_at=row["promoted_at"],
            retired_at=row["retired_at"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)


class ThresholdConfigRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_for_segment(self, segment_key: str) -> ThresholdConfig | None:
        row = await self.database.require_pool().fetchrow(
            """
            select * from threshold_config
            where (segment_key = $1 or segment_key = 'default') and enabled = true
            order by case when segment_key = $1 then 0 else 1 end
            limit 1
            """,
            segment_key,
        )
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[ThresholdConfig]:
        rows = await self.database.require_pool().fetch(
            "select * from threshold_config order by segment_key"
        )
        return [self._to_domain(row) for row in rows]

    async def upsert(
        self,
        segment_key: str,
        block_threshold: float,
        review_threshold: float,
        approve_threshold: float,
    ) -> ThresholdConfig:
        row = await self.database.require_pool().fetchrow(
            """
            insert into threshold_config (segment_key, block_threshold, review_threshold, approve_threshold)
            values ($1, $2, $3, $4)
            on conflict (segment_key) do update set
                block_threshold = excluded.block_threshold,
                review_threshold = excluded.review_threshold,
                approve_threshold = excluded.approve_threshold,
                updated_at = now()
            returning *
            """,
            segment_key, block_threshold, review_threshold, approve_threshold,
        )
        return self._to_domain(row)

    def _to_domain(self, row) -> ThresholdConfig:
        return ThresholdConfig(
            id=row["id"],
            segment_key=row["segment_key"],
            block_threshold=float(row["block_threshold"]),
            review_threshold=float(row["review_threshold"]),
            approve_threshold=float(row["approve_threshold"]),
            enabled=row["enabled"],
            updated_at=row["updated_at"],
        )


class ModelKillSwitchRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_for_provider(self, provider_key: str) -> ModelKillSwitch | None:
        row = await self.database.require_pool().fetchrow(
            "select * from model_kill_switch where provider_key = $1",
            provider_key,
        )
        return self._to_domain(row) if row else None

    async def activate(self, provider_key: str, reason: str, activated_by: str) -> ModelKillSwitch:
        row = await self.database.require_pool().fetchrow(
            """
            insert into model_kill_switch (provider_key, active, reason, activated_by, activated_at, updated_at)
            values ($1, true, $2, $3, now(), now())
            on conflict (provider_key) do update set
                active = true,
                reason = excluded.reason,
                activated_by = excluded.activated_by,
                activated_at = now(),
                deactivated_at = null,
                updated_at = now()
            returning *
            """,
            provider_key, reason, activated_by,
        )
        return self._to_domain(row)

    async def deactivate(self, provider_key: str) -> ModelKillSwitch | None:
        row = await self.database.require_pool().fetchrow(
            """
            update model_kill_switch
            set active = false, deactivated_at = now(), updated_at = now()
            where provider_key = $1
            returning *
            """,
            provider_key,
        )
        return self._to_domain(row) if row else None

    async def is_active(self, provider_key: str) -> bool:
        switch = await self.get_for_provider(provider_key)
        return switch is not None and switch.active

    def _to_domain(self, row) -> ModelKillSwitch:
        return ModelKillSwitch(
            id=row["id"],
            provider_key=row["provider_key"],
            active=row["active"],
            reason=row["reason"],
            activated_by=row["activated_by"],
            activated_at=row["activated_at"],
            deactivated_at=row["deactivated_at"],
            updated_at=row["updated_at"],
        )


class ReplayRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        challenger_model_id: UUID,
        baseline_model_id: UUID | None,
        event_window_start,
        event_window_end,
    ) -> ReplayRun:
        row = await self.database.require_pool().fetchrow(
            """
            insert into replay_runs
                (challenger_model_id, baseline_model_id, event_window_start, event_window_end)
            values ($1, $2, $3, $4)
            returning *
            """,
            challenger_model_id, baseline_model_id, event_window_start, event_window_end,
        )
        return self._to_domain(row)

    async def update_status(
        self,
        run_id: UUID,
        status: ReplayStatus,
        processed_events: int | None = None,
        result_summary: dict | None = None,
    ) -> ReplayRun | None:
        row = await self.database.require_pool().fetchrow(
            """
            update replay_runs
            set status = $2,
                processed_events = coalesce($3, processed_events),
                result_summary = coalesce($4::jsonb, result_summary),
                started_at = case when $2 = 'RUNNING' and started_at is null then now() else started_at end,
                completed_at = case when $2 in ('COMPLETED','FAILED','CANCELLED') then now() else completed_at end
            where id = $1
            returning *
            """,
            run_id,
            status.value,
            processed_events,
            json.dumps(result_summary) if result_summary else None,
        )
        return self._to_domain(row) if row else None

    async def get_by_id(self, run_id: UUID) -> ReplayRun | None:
        row = await self.database.require_pool().fetchrow(
            "select * from replay_runs where id = $1", run_id
        )
        return self._to_domain(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[ReplayRun]:
        rows = await self.database.require_pool().fetch(
            "select * from replay_runs order by created_at desc limit $1", limit
        )
        return [self._to_domain(row) for row in rows]

    def _to_domain(self, row) -> ReplayRun:
        return ReplayRun(
            id=row["id"],
            challenger_model_id=row["challenger_model_id"],
            baseline_model_id=row["baseline_model_id"],
            status=ReplayStatus(row["status"]),
            event_window_start=row["event_window_start"],
            event_window_end=row["event_window_end"],
            total_events=row["total_events"],
            processed_events=row["processed_events"],
            result_summary=self._json_dict(row["result_summary"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            created_at=row["created_at"],
        )

    def _json_dict(self, value) -> dict:
        if isinstance(value, dict):
            return value
        return json.loads(value)
