"""
Model governance service: promote/demote/retire models through the lifecycle.
Enforces the candidate -> shadow -> canary -> primary progression.
"""
import logging
from uuid import UUID

from app.domain.models import AuditAction, ModelRegistry, ModelStage
from app.infrastructure.repositories import (
    AuditLogRepository,
    ModelKillSwitchRepository,
    ModelRegistryRepository,
)

logger = logging.getLogger(__name__)

_VALID_PROMOTIONS: dict[ModelStage, set[ModelStage]] = {
    ModelStage.CANDIDATE: {ModelStage.SHADOW},
    ModelStage.SHADOW: {ModelStage.CANARY},
    ModelStage.CANARY: {ModelStage.PRIMARY},
    ModelStage.PRIMARY: {ModelStage.RETIRED},
    ModelStage.RETIRED: set(),
}


class ModelGovernanceService:
    def __init__(
        self,
        registry_repo: ModelRegistryRepository,
        kill_switch_repo: ModelKillSwitchRepository,
        audit_repo: AuditLogRepository,
    ) -> None:
        self.registry_repo = registry_repo
        self.kill_switch_repo = kill_switch_repo
        self.audit_repo = audit_repo

    async def register(
        self,
        name: str,
        version: str,
        provider: str,
        config: dict,
    ) -> ModelRegistry:
        model = await self.registry_repo.create(
            name=name,
            version=version,
            provider=provider,
            config=config,
            stage=ModelStage.CANDIDATE,
        )
        logger.info("Registered model %s v%s as CANDIDATE id=%s", name, version, model.id)
        return model

    async def promote(self, model_id: UUID, target_stage: ModelStage, actor: str) -> ModelRegistry:
        model = await self.registry_repo.get_by_id(model_id)
        if model is None:
            raise ValueError(f"Model {model_id} not found")

        allowed = _VALID_PROMOTIONS.get(model.stage, set())
        if target_stage not in allowed:
            raise ValueError(
                f"Cannot promote from {model.stage} to {target_stage}. "
                f"Allowed targets: {allowed}"
            )

        # When promoting to PRIMARY, retire any existing primary
        if target_stage == ModelStage.PRIMARY:
            current_primary = await self.registry_repo.get_primary()
            if current_primary and current_primary.id != model_id:
                await self.registry_repo.retire(current_primary.id)
                await self.audit_repo.create(
                    ticket_id=None,
                    actor=actor,
                    action=AuditAction.MODEL_RETIRED,
                    details={"model_id": str(current_primary.id), "reason": "superseded_by_promotion"},
                )

        promoted = await self.registry_repo.promote(model_id, target_stage)
        if promoted is None:
            raise RuntimeError(f"Failed to promote model {model_id}")

        await self.audit_repo.create(
            ticket_id=None,
            actor=actor,
            action=AuditAction.MODEL_PROMOTED,
            details={
                "model_id": str(model_id),
                "from_stage": model.stage.value,
                "to_stage": target_stage.value,
            },
        )
        logger.info("Model %s promoted from %s to %s by %s", model_id, model.stage, target_stage, actor)
        return promoted

    async def retire(self, model_id: UUID, actor: str) -> ModelRegistry:
        model = await self.registry_repo.retire(model_id)
        if model is None:
            raise ValueError(f"Model {model_id} not found")
        await self.audit_repo.create(
            ticket_id=None,
            actor=actor,
            action=AuditAction.MODEL_RETIRED,
            details={"model_id": str(model_id)},
        )
        return model

    async def activate_kill_switch(
        self, provider_key: str, reason: str, activated_by: str
    ) -> None:
        await self.kill_switch_repo.activate(provider_key, reason, activated_by)
        await self.audit_repo.create(
            ticket_id=None,
            actor=activated_by,
            action=AuditAction.KILL_SWITCH_ACTIVATED,
            details={"provider_key": provider_key, "reason": reason},
        )
        logger.warning("Kill switch ACTIVATED for provider %s by %s: %s", provider_key, activated_by, reason)

    async def deactivate_kill_switch(self, provider_key: str, actor: str) -> None:
        await self.kill_switch_repo.deactivate(provider_key)
        await self.audit_repo.create(
            ticket_id=None,
            actor=actor,
            action=AuditAction.KILL_SWITCH_DEACTIVATED,
            details={"provider_key": provider_key},
        )
        logger.info("Kill switch DEACTIVATED for provider %s by %s", provider_key, actor)

    async def list_models(self) -> list[ModelRegistry]:
        return await self.registry_repo.list_all()

    async def get_primary(self) -> ModelRegistry | None:
        return await self.registry_repo.get_primary()
