"""Shared types for the core-satellite-overlay architecture (03 §5.3, 09 §1).

Every signal source—rule strategies (core C1-C3, satellite S-A), LLM scorers
(S-B/S-C) and future NN scorers—implements the same :class:`SignalProvider`
protocol and emits the same :class:`Inference` / :class:`ExplainContract`
objects, so the evaluation and governance pipeline (09) is model-agnostic.

Strategies produce a desired :class:`TargetPortfolio`; the M8 risk engine
(``yquant.risk``) turns it into a controlled one before M5 builds proposals.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from yquant.datasrc.protocols import DataRepo

# The three portfolio layers of the v3.1a architecture (03 §3).
Layer = Literal["core", "satellite", "overlay"]

# Provider kinds drive the J3 contamination rule (09 §2, ADR-24): only
# llm / ml_blackbox providers require a knowledge_cutoff and have their
# pre-cutoff evaluation samples marked contaminated.
ProviderKind = Literal["rule", "llm", "ml_blackbox"]

# Tolerance for the no-leverage weight-sum check (float accumulation slack).
_WEIGHT_EPS = 1e-9


class TargetPortfolio(BaseModel):
    """A desired or risk-controlled set of target weights.

    ``weights`` maps symbol -> target weight in [0, 1]; ``cash_weight`` is the
    residual held in cash. Invested weights plus cash must not exceed 1 — v1 is
    long-only with no leverage (03 §5.3 C3 / §5.8 ①). ``layers`` tags each symbol
    so the risk engine can act per layer (e.g. halve the satellite layer on the
    circuit-breaker ladder).
    """

    as_of: date
    weights: dict[str, float] = Field(default_factory=dict)
    layers: dict[str, Layer] = Field(default_factory=dict)
    cash_weight: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _check_no_leverage(self) -> TargetPortfolio:
        for symbol, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"weight for {symbol} must be non-negative (v1 is long-only)")
            if weight > 1:
                raise ValueError(f"weight for {symbol} must not exceed 1")
        total = sum(self.weights.values()) + self.cash_weight
        if total > 1 + _WEIGHT_EPS:
            raise ValueError(f"total invested weight {total:.6f} exceeds 1 (no leverage)")
        return self

    def invested_weight(self) -> float:
        """Total weight allocated to positions (excludes cash)."""

        return sum(self.weights.values())

    def layer_weight(self, layer: Layer) -> float:
        """Total invested weight belonging to one layer."""

        return sum(w for symbol, w in self.weights.items() if self.layers.get(symbol) == layer)


class ExplainContract(BaseModel):
    """Mandatory explanation object attached to every inference (09 §4).

    The ledger refuses any inference without one. ``ood_score`` is required for
    ``ml_blackbox`` providers; ``caveats`` must always carry at least one entry.
    """

    kind: ProviderKind
    confidence: float = Field(ge=0, le=1)
    ood_score: float | None = None
    regime_tag: str
    evidence: list[str] = Field(default_factory=list)
    similar_history: list[str] = Field(default_factory=list)
    caveats: list[str]

    @model_validator(mode="after")
    def _check_contract(self) -> ExplainContract:
        if not self.caveats:
            raise ValueError("caveats must contain at least one entry (09 §4)")
        if self.kind == "ml_blackbox" and self.ood_score is None:
            raise ValueError("ood_score is required for ml_blackbox providers (09 §4)")
        return self


class Inference(BaseModel):
    """A single signal-source output for one symbol (09 §1).

    ``output`` is either a continuous score or a discrete action. ``confidence``
    is mandatory — a model that cannot estimate its own uncertainty is not
    admissible (09 §1).
    """

    symbol: str
    output: float | Literal["buy", "sell", "hold", "abstain"]
    confidence: float = Field(ge=0, le=1)
    explain: ExplainContract


class ModelCard(BaseModel):
    """Provider registration card (09 §1); stored and shown in the UI.

    ``knowledge_cutoff`` is mandatory for ``llm`` / ``ml_blackbox`` providers
    (ADR-24): the evaluation pipeline splits samples on it and marks anything
    before as ``contaminated``. Rule providers may leave it ``None``.
    """

    provider_id: str
    kind: ProviderKind
    purpose: str
    inputs: list[str]
    owner: str
    training_window: tuple[date, date] | None = None
    knowledge_cutoff: date | None = None
    known_limits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    eval_report_ref: str = ""

    @model_validator(mode="after")
    def _check_cutoff(self) -> ModelCard:
        if self.kind in {"llm", "ml_blackbox"} and self.knowledge_cutoff is None:
            raise ValueError(
                "knowledge_cutoff is required for llm/ml_blackbox providers (ADR-24, 09 §2)"
            )
        return self


@runtime_checkable
class SignalProvider(Protocol):
    """The one protocol every signal source implements (09 §1).

    Providers never emit orders (ADR-22); they emit scored inferences that the
    strategy/risk layers translate into controlled target weights.
    """

    provider_id: str

    def predict(self, as_of: date, universe: list[str], repo: DataRepo) -> list[Inference]:
        """Return one inference per acted-on symbol as of ``as_of``."""

    def model_card(self) -> ModelCard:
        """Return the registration card describing this provider."""
