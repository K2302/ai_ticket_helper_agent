"""
Replay / backtest service: runs historical ticket events through a challenger
model to compare its decisions against the current primary, without affecting
live traffic.
"""
import logging
from datetime import datetime
from uuid import UUID

from app.domain.models import AuditAction, ReplayRun, ReplayStatus
from app.infrastructure.repositories import (
    AuditLogRepository,
    ModelRegistryRepository,
    ReplayRunRepository,
    RiskDecisionRepository,
)
from app.services.feature_extractor import FeatureExtractor
from app.services.policy_engine import PolicyEngine, score_to_decision

logger = logging.getLogger(__name__)


class ReplayService:
    def __init__(
        self,
        replay_repo: ReplayRunRepository,
        risk_decision_repo: RiskDecisionRepository,
        model_registry_repo: ModelRegistryRepository,
        audit_repo: AuditLogRepository,
        feature_extractor: FeatureExtractor,
        policy_engine: PolicyEngine,
    ) -> None:
        self.replay_repo = replay_repo
        self.risk_decision_repo = risk_decision_repo
        self.model_registry_repo = model_registry_repo
        self.audit_repo = audit_repo
        self.feature_extractor = feature_extractor
        self.policy_engine = policy_engine

    async def create_run(
        self,
        challenger_model_id: UUID,
        baseline_model_id: UUID | None,
        event_window_start: datetime,
        event_window_end: datetime,
        actor: str,
    ) -> ReplayRun:
        run = await self.replay_repo.create(
            challenger_model_id=challenger_model_id,
            baseline_model_id=baseline_model_id,
            event_window_start=event_window_start,
            event_window_end=event_window_end,
        )
        await self.audit_repo.create(
            ticket_id=None,
            actor=actor,
            action=AuditAction.REPLAY_STARTED,
            details={
                "replay_run_id": str(run.id),
                "challenger_model_id": str(challenger_model_id),
                "baseline_model_id": str(baseline_model_id) if baseline_model_id else None,
                "window_start": event_window_start.isoformat(),
                "window_end": event_window_end.isoformat(),
            },
        )
        return run

    async def execute_run(self, run_id: UUID) -> ReplayRun:
        """
        Loads historical risk decisions in the window and re-scores them
        using the challenger model's thresholds. Stores aggregate comparison
        in result_summary on the replay run.
        """
        run = await self.replay_repo.get_by_id(run_id)
        if run is None:
            raise ValueError(f"Replay run {run_id} not found")

        await self.replay_repo.update_status(run_id, ReplayStatus.RUNNING)

        challenger = await self.model_registry_repo.get_by_id(run.challenger_model_id)
        if challenger is None:
            await self.replay_repo.update_status(run_id, ReplayStatus.FAILED)
            raise ValueError(f"Challenger model {run.challenger_model_id} not found")

        # Load historical decisions within the replay window
        historical = await self._fetch_decisions_in_window(
            run.event_window_start, run.event_window_end
        )

        agree = 0
        disagree = 0
        decision_shifts: dict[str, int] = {}

        for original_decision in historical:
            # Re-score using challenger model with default thresholds
            replay_outcome, _ = score_to_decision(
                original_decision.score,
                block_threshold=challenger.config.get("block_threshold", 0.80),
                review_threshold=challenger.config.get("review_threshold", 0.50),
            )
            if replay_outcome == original_decision.decision:
                agree += 1
            else:
                disagree += 1
                key = f"{original_decision.decision.value}->{replay_outcome.value}"
                decision_shifts[key] = decision_shifts.get(key, 0) + 1

            # Persist replay decision sample
            await self.database_execute_replay_sample(
                run_id, original_decision, replay_outcome
            )

        total = len(historical)
        result_summary = {
            "total": total,
            "agree": agree,
            "disagree": disagree,
            "agreement_rate": round(agree / total, 4) if total else None,
            "decision_shifts": decision_shifts,
        }

        completed = await self.replay_repo.update_status(
            run_id,
            ReplayStatus.COMPLETED,
            processed_events=total,
            result_summary=result_summary,
        )
        assert completed is not None

        await self.audit_repo.create(
            ticket_id=None,
            actor="replay-service",
            action=AuditAction.REPLAY_COMPLETED,
            details={"replay_run_id": str(run_id), **result_summary},
        )
        return completed

    async def _fetch_decisions_in_window(self, start: datetime, end: datetime):
        rows = await self.risk_decision_repo.database.require_pool().fetch(
            """
            select * from risk_decisions
            where created_at >= $1 and created_at <= $2
            order by created_at
            """,
            start, end,
        )
        from app.domain.models import RiskDecision, RiskDecisionOutcome
        import json

        results = []
        for row in rows:
            results.append(RiskDecision(
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
                feature_snapshot=row["feature_snapshot"] if isinstance(row["feature_snapshot"], dict) else json.loads(row["feature_snapshot"]),
                feature_snapshot_hash=row["feature_snapshot_hash"],
                explainability=row["explainability"] if isinstance(row["explainability"], dict) else json.loads(row["explainability"]),
                model_version=row["model_version"],
                created_at=row["created_at"],
            ))
        return results

    async def database_execute_replay_sample(self, run_id, original_decision, replay_outcome) -> None:
        from app.domain.models import RiskDecisionOutcome
        score_delta = None  # In replay we re-use the same score; delta from original decision is directional
        await self.risk_decision_repo.database.require_pool().execute(
            """
            insert into replay_decisions
                (replay_run_id, ticket_id, original_decision, replay_decision, score_delta)
            values ($1, $2, $3, $4, $5)
            """,
            run_id,
            original_decision.ticket_id,
            original_decision.decision.value,
            replay_outcome.value,
            score_delta,
        )

    async def get_run(self, run_id: UUID) -> ReplayRun | None:
        return await self.replay_repo.get_by_id(run_id)

    async def list_runs(self) -> list[ReplayRun]:
        return await self.replay_repo.list_recent()
