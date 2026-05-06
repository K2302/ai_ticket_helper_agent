"""
Online model monitor: records per-decision samples and computes
drift + calibration metrics from reviewed samples.
"""
import logging
from uuid import UUID

from app.domain.models import RiskDecision, RiskDecisionOutcome
from app.infrastructure.db import Database

logger = logging.getLogger(__name__)


class ModelMonitorService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def record_sample(
        self,
        risk_decision: RiskDecision,
        segment: str,
        baseline_score: float | None = None,
    ) -> None:
        score_delta = None
        if baseline_score is not None:
            score_delta = round(risk_decision.score - baseline_score, 4)
            is_drift = abs(score_delta) > 0.20
        else:
            is_drift = False

        await self.database.require_pool().execute(
            """
            insert into model_monitor_samples (
                risk_decision_id, model_registry_id, predicted_decision,
                score, score_delta, is_drift_flagged, segment
            ) values ($1, $2, $3, $4, $5, $6, $7)
            """,
            risk_decision.id,
            risk_decision.model_registry_id,
            risk_decision.decision.value,
            risk_decision.score,
            score_delta,
            is_drift,
            segment,
        )
        if is_drift:
            logger.warning(
                "Drift detected for model_registry_id=%s decision=%s score_delta=%.4f",
                risk_decision.model_registry_id,
                risk_decision.decision.value,
                score_delta,
            )

    async def update_actual_outcome(
        self,
        risk_decision_id: UUID,
        actual_outcome: str,
    ) -> None:
        await self.database.require_pool().execute(
            """
            update model_monitor_samples
            set actual_outcome = $2
            where risk_decision_id = $1
            """,
            risk_decision_id,
            actual_outcome,
        )

    async def get_metrics(self, model_registry_id: UUID, limit: int = 1000) -> dict:
        rows = await self.database.require_pool().fetch(
            """
            select predicted_decision, actual_outcome, score, is_drift_flagged
            from model_monitor_samples
            where model_registry_id = $1
            order by sampled_at desc
            limit $2
            """,
            model_registry_id,
            limit,
        )
        total = len(rows)
        if total == 0:
            return {"total_samples": 0}

        drift_count = sum(1 for r in rows if r["is_drift_flagged"])
        reviewed = [r for r in rows if r["actual_outcome"] is not None]
        correct = sum(
            1 for r in reviewed
            if r["predicted_decision"] == r["actual_outcome"]
        )

        decision_dist: dict[str, int] = {}
        for r in rows:
            decision_dist[r["predicted_decision"]] = decision_dist.get(r["predicted_decision"], 0) + 1

        return {
            "total_samples": total,
            "drift_flagged": drift_count,
            "drift_rate": round(drift_count / total, 4),
            "reviewed_samples": len(reviewed),
            "accuracy": round(correct / len(reviewed), 4) if reviewed else None,
            "decision_distribution": decision_dist,
        }
