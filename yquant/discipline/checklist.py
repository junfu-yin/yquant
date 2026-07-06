"""M5 execution checklist (03 §5.5).

Six mandatory items must all be satisfied before a proposal can be marked
"executed" (UI enforces the gate; this module owns the data model + the gate
logic so it is unit-testable). Item ① requires an off-plan reason when the trade
was not triggered by an established strategy rule; that reason feeds the weekly
review.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionChecklist:
    """The six §5.5 checklist items and their state.

    - ``triggered_by_rule``: was this triggered by an established strategy rule?
      If False, ``off_plan_reason`` becomes mandatory.
    - ``not_in_cooldown``: confirmed not in a consecutive-loss cooldown (or
      explicitly overridden after reading the warning).
    - ``within_single_name_cap``: post-trade single-name weight within cap.
    - ``within_layer_budget``: post-trade layer/Overlay budget remains compliant.
    - ``drawdown_allows_add``: portfolio drawdown state permits this add.
    - ``red_flags_reviewed``: today's red-flag events for the symbol were read.
    - ``red_team_reviewed``: the red-team note was read before confirmation.
    """

    triggered_by_rule: bool = False
    off_plan_reason: str = ""
    not_in_cooldown: bool = False
    within_single_name_cap: bool = False
    within_layer_budget: bool = False
    drawdown_allows_add: bool = False
    red_flags_reviewed: bool = False
    red_team_reviewed: bool = False
    overrides: list[str] = field(default_factory=list)

    def unmet_items(self) -> list[str]:
        """Return the checklist items still blocking execution."""

        unmet: list[str] = []
        if not self.triggered_by_rule and not self.off_plan_reason.strip():
            unmet.append("off_plan_reason_required")
        if not self.not_in_cooldown:
            unmet.append("not_in_cooldown")
        if not self.within_single_name_cap or not self.within_layer_budget:
            unmet.append("within_position_and_layer_budget")
        if not self.drawdown_allows_add:
            unmet.append("drawdown_allows_add")
        if not self.red_flags_reviewed:
            unmet.append("red_flags_reviewed")
        if not self.red_team_reviewed:
            unmet.append("red_team_reviewed")
        return unmet

    def is_complete(self) -> bool:
        """Whether every mandatory item is satisfied (gate for "executed")."""

        return not self.unmet_items()

    def to_json(self) -> dict[str, object]:
        """Serialize for the ``proposals.checklist_json`` column (03 §7)."""

        return {
            "triggered_by_rule": self.triggered_by_rule,
            "off_plan_reason": self.off_plan_reason,
            "not_in_cooldown": self.not_in_cooldown,
            "within_single_name_cap": self.within_single_name_cap,
            "within_layer_budget": self.within_layer_budget,
            "drawdown_allows_add": self.drawdown_allows_add,
            "red_flags_reviewed": self.red_flags_reviewed,
            "red_team_reviewed": self.red_team_reviewed,
            "overrides": list(self.overrides),
            "complete": self.is_complete(),
        }
