from app.domain.models import Category, EscalationRisk, Priority

# Teams that are canonical outputs from the triage tree nodes.
# Defined here so routing.py and triage_tree.py share the same set.
TEAM_ESCALATIONS = "Escalations"
TEAM_BILLING = "Billing Support"
TEAM_ACCOUNT = "Account Support"
TEAM_ENGINEERING = "Engineering L1"
TEAM_TECHNICAL = "Technical Support"
TEAM_PRODUCT = "Product & Success"
TEAM_CUSTOMER = "Customer Support"


class RoutingEngine:
    def route(
        self,
        category: Category,
        priority: Priority,
        escalation_risk: EscalationRisk,
        target_team_hint: str | None = None,
    ) -> str:
        """
        Return the assigned team.

        Priority order:
        1. Hard escalation override (URGENT / HIGH risk) → always Escalations.
        2. Tree-derived hint (from LLM decision_path or classifier_with_tree). 
        3. Category-based fallback.
        """
        if escalation_risk == EscalationRisk.HIGH or priority == Priority.URGENT:
            return TEAM_ESCALATIONS

        # Accept hint only from the known set of tree teams
        _VALID_TREE_TEAMS = {
            TEAM_BILLING, TEAM_ACCOUNT, TEAM_ENGINEERING,
            TEAM_PRODUCT, TEAM_CUSTOMER,
        }
        if target_team_hint and target_team_hint in _VALID_TREE_TEAMS:
            return target_team_hint

        # Fallback: category-based
        if category == Category.BILLING:
            return TEAM_BILLING
        if category == Category.ACCOUNT_ACCESS:
            return TEAM_ACCOUNT
        if category in {Category.BUG_REPORT, Category.TECHNICAL_SUPPORT}:
            return TEAM_TECHNICAL
        return TEAM_CUSTOMER
