"""Provenance envelope + decision-event schemas (07 §2, ADR-13).

Every business-meaningful fact enters the append-only ledger wrapped in an
:class:`Event`. The envelope is *strongly validated*: a write that lacks the
provenance a replay would need is rejected at construction time, not silently
persisted. "无凭证，不决策" is therefore an architectural property, not a
convention someone can forget.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

EventKind = Literal[
    "data_ingested",
    "event_card",
    "signal",
    "proposal",
    "order",
    "fill",
    "risk_trigger",
    "alert",
    "human_action",
    "job_status",
    "model_inference",
    # v3.1 增量 (07 §2 ◆)
    "macro_event_card",
    "regime_change",
    "committee_output",
    "thesis_check",
    "overlay_budget_reject",
]

# Kinds that involve an LLM/model call must carry prompt_version + model_id.
_LLM_KINDS: frozenset[str] = frozenset(
    {
        "event_card",
        "macro_event_card",
        "committee_output",
        "model_inference",
    }
)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class Provenance(BaseModel):
    """Fixed provenance shell every event carries (07 §2).

    ``model_id`` for v3.1 must encode supplier + version + knowledge_cutoff so
    the incident playbook's model-layer bisection can spot contaminating
    look-back (ADR-24 / 09 联动).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    git_sha: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    data_manifest_id: str = Field(min_length=1)
    prompt_version: str | None = None
    model_id: str | None = None
    seed: int | None = None


class Event(BaseModel):
    """One append-only decision-event with its provenance envelope (07 §2)."""

    model_config = {"frozen": True, "extra": "forbid"}

    event_id: str = Field(min_length=1)
    ts: datetime
    kind: EventKind
    payload: dict[str, Any]
    run_id: str = Field(min_length=1)
    dedup_key: str = Field(min_length=1)
    provenance: Provenance
    causation_id: str | None = None

    @model_validator(mode="after")
    def _enforce_provenance_completeness(self) -> Event:
        prov = self.provenance
        if self.kind in _LLM_KINDS:
            if not prov.prompt_version:
                raise ValueError(f"{self.kind} events require provenance.prompt_version")
            if not prov.model_id:
                raise ValueError(f"{self.kind} events require provenance.model_id")
        if prov.model_id is not None and "cutoff=" not in prov.model_id:
            raise ValueError(
                "model_id must encode a knowledge cutoff, e.g. 'deepseek-v3@cutoff=2024-07'"
            )
        return self

    @model_validator(mode="after")
    def _enforce_utc(self) -> Event:
        if self.ts.tzinfo is None:
            raise ValueError("event ts must be timezone-aware UTC")
        return self

    def canonical_bytes(self) -> bytes:
        """Deterministic serialization used for the run-digest Merkle leaf.

        Timestamps normalise to UTC ISO8601; keys are sorted so two logically
        identical events hash identically regardless of field insertion order.
        """

        body = {
            "event_id": self.event_id,
            "ts": self.ts.astimezone(UTC).isoformat(),
            "kind": self.kind,
            "payload": self.payload,
            "run_id": self.run_id,
            "dedup_key": self.dedup_key,
            "causation_id": self.causation_id,
            "provenance": self.provenance.model_dump(),
        }
        return json.dumps(body, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")


def new_event_id(ts: datetime | None = None, *, entropy: bytes | None = None) -> str:
    """Generate a time-ordered ULID-style id (Crockford base32, 26 chars).

    Explicit ``entropy`` makes the id deterministic for tests; production callers
    omit it and get 80 bits from the OS CSPRNG.
    """

    moment = ts or datetime.now(UTC)
    millis = int(moment.astimezone(UTC).timestamp() * 1000) & ((1 << 48) - 1)
    rand = entropy if entropy is not None else os.urandom(10)
    if len(rand) != 10:
        raise ValueError("entropy must be exactly 10 bytes (80 bits)")
    value = (millis << 80) | int.from_bytes(rand, "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def make_dedup_key(kind: str, *parts: object) -> str:
    """Build the idempotency key (T8): ``kind:part:part…`` with stable ordering."""

    tail = ":".join(str(part) for part in parts)
    return f"{kind}:{tail}" if tail else kind
