"""Model governance panel: the four-piece board the UI renders (09 §8).

Assembles one :class:`ProviderGovernanceRow` per registered provider from its
ModelCard plus (optionally) its offline J3-split report and black-box profile,
then rolls the rows into a single JSON-safe :class:`ModelGovernancePanel` with a
blocking verdict. The gate mirrors the doctrine:

* an LLM/ML card without ``knowledge_cutoff`` or ``data_dependencies`` is invalid
  (blocks — but such a card cannot even be constructed, so this is belt-and-braces);
* a provider whose offline evidence is *entirely contaminated* (no credited
  samples) may not be promoted;
* a provider whose behavior tests are red blocks the gate.

The contamination flag is always surfaced (09 §8 "contaminated 标记 … 强制性").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from yquant.governance.blackbox import BlackBoxProfile
from yquant.governance.evaluation import OfflineEvaluationReport
from yquant.strategies.base import ModelCard


@dataclass(frozen=True)
class ProviderGovernanceRow:
    """One provider's governance state: card + eval + black-box, with a verdict."""

    card: ModelCard
    offline: OfflineEvaluationReport | None
    blackbox: BlackBoxProfile | None
    is_trading: bool

    @property
    def contaminated(self) -> bool:
        return bool(self.offline and self.offline.has_contamination)

    @property
    def promotable(self) -> bool:
        """Whether this provider's evidence permits promotion (09 §2/§6).

        Requires: a valid card (guaranteed by construction), at least one
        credited (non-contaminated) offline sample when an offline report is
        present, and green behavior tests when a black-box profile is present.
        """

        if self.offline is not None and self.offline.credited.count == 0:
            return False
        return not (self.blackbox is not None and not self.blackbox.behavior_all_green)

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.card.provider_id,
            "kind": self.card.kind,
            "purpose": self.card.purpose,
            "owner": self.card.owner,
            "is_trading": self.is_trading,
            "knowledge_cutoff": (
                self.card.knowledge_cutoff.isoformat()
                if self.card.knowledge_cutoff
                else None
            ),
            "data_dependencies": list(self.card.data_dependencies),
            "contaminated": self.contaminated,
            "promotable": self.promotable,
            "offline": self.offline.as_dict() if self.offline else None,
            "blackbox": self.blackbox.as_dict() if self.blackbox else None,
        }


@dataclass(frozen=True)
class ModelGovernancePanel:
    """The registry-wide governance board with a single blocking verdict (09 §8)."""

    rows: tuple[ProviderGovernanceRow, ...]

    @property
    def any_contaminated(self) -> bool:
        return any(r.contaminated for r in self.rows)

    @property
    def blocked_provider_ids(self) -> tuple[str, ...]:
        return tuple(r.card.provider_id for r in self.rows if not r.promotable)

    @property
    def passed(self) -> bool:
        """Green only when every provider is promotable (contamination is a warning)."""

        return not self.blocked_provider_ids

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "total": len(self.rows),
            "any_contaminated": self.any_contaminated,
            "blocked_provider_ids": list(self.blocked_provider_ids),
            "providers": [r.as_dict() for r in self.rows],
        }

    def render_text(self) -> str:
        lines = ["model governance panel:"]
        for r in self.rows:
            mark = "OK" if r.promotable else "BLOCK"
            contam = " [contaminated]" if r.contaminated else ""
            trading = "trading" if r.is_trading else "non-trading"
            lines.append(f"  [{mark}] {r.card.provider_id} ({trading}){contam}")
        lines.append(f"verdict: {'GREEN' if self.passed else 'RED'}")
        return "\n".join(lines)


def build_governance_panel(
    cards: Sequence[ModelCard],
    *,
    offline_reports: dict[str, OfflineEvaluationReport] | None = None,
    blackbox_profiles: dict[str, BlackBoxProfile] | None = None,
    non_trading_ids: Sequence[str] = (),
) -> ModelGovernancePanel:
    """Assemble a governance panel from cards + optional evidence, ordered by id.

    ``non_trading_ids`` marks the three non-trading providers (hawk/dove scorer,
    event-card factory, Thesis sentinel) that are registered and evaluated but
    hold no budget (09 §1 ◆).
    """

    offline_reports = offline_reports or {}
    blackbox_profiles = blackbox_profiles or {}
    non_trading = set(non_trading_ids)
    rows: list[ProviderGovernanceRow] = []
    for card in sorted(cards, key=lambda c: c.provider_id):
        rows.append(
            ProviderGovernanceRow(
                card=card,
                offline=offline_reports.get(card.provider_id),
                blackbox=blackbox_profiles.get(card.provider_id),
                is_trading=card.provider_id not in non_trading,
            )
        )
    return ModelGovernancePanel(rows=tuple(rows))


__all__ = [
    "ModelGovernancePanel",
    "ProviderGovernanceRow",
    "build_governance_panel",
]
