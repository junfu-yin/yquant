"""WP7 decision-event ledger + provenance envelope tests (07 §2, §4)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from yquant.ledger import (
    Event,
    LedgerStore,
    Provenance,
    compute_merkle_root,
    make_dedup_key,
    new_event_id,
)


def _prov(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "git_sha": "abc123",
        "config_hash": "cfg-1",
        "data_manifest_id": "mani-1",
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def _event(
    *,
    kind: str = "signal",
    ts: datetime | None = None,
    dedup_key: str = "signal:2024-01-03:SPY",
    provenance: Provenance | None = None,
    causation_id: str | None = None,
    event_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> Event:
    moment = ts or datetime(2024, 1, 3, 12, 0, tzinfo=UTC)
    return Event(
        event_id=event_id or new_event_id(moment, entropy=b"0123456789"),
        ts=moment,
        kind=kind,  # type: ignore[arg-type]
        payload=payload or {"symbol": "SPY", "weight": 0.5},
        run_id="run-2024-01-03",
        dedup_key=dedup_key,
        provenance=provenance or _prov(),
        causation_id=causation_id,
    )


# ---- Envelope strong validation (07 §2, ADR-13) -------------------------


def test_provenance_rejects_empty_required_field() -> None:
    with pytest.raises(ValidationError):
        Provenance(git_sha="", config_hash="c", data_manifest_id="m")


def test_llm_kind_requires_prompt_version_and_model_id() -> None:
    # event_card is an LLM kind: missing prompt_version must be rejected.
    with pytest.raises(ValidationError):
        _event(
            kind="event_card",
            provenance=_prov(model_id="deepseek-v3@cutoff=2024-07"),
        )


def test_llm_kind_requires_model_id() -> None:
    with pytest.raises(ValidationError):
        _event(kind="event_card", provenance=_prov(prompt_version="p1"))


def test_model_id_must_encode_knowledge_cutoff() -> None:
    with pytest.raises(ValidationError):
        _event(
            kind="model_inference",
            provenance=_prov(prompt_version="p1", model_id="deepseek-v3"),
        )


def test_llm_kind_accepts_full_provenance() -> None:
    event = _event(
        kind="committee_output",
        dedup_key="committee_output:2024-01-03",
        provenance=_prov(prompt_version="p2", model_id="dsk@cutoff=2024-07"),
    )
    assert event.kind == "committee_output"


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _event(ts=datetime(2024, 1, 3, 12, 0))


def test_extra_field_is_forbidden() -> None:
    with pytest.raises(ValidationError):
        Event(
            event_id="x",
            ts=datetime(2024, 1, 3, tzinfo=UTC),
            kind="signal",
            payload={},
            run_id="r",
            dedup_key="k",
            provenance=_prov(),
            surprise="boom",  # type: ignore[call-arg]
        )


def test_v31_kind_extension_is_accepted() -> None:
    for kind in ("regime_change", "thesis_check", "overlay_budget_reject"):
        event = _event(kind=kind, dedup_key=f"{kind}:2024-01-03")
        assert event.kind == kind


# ---- new_event_id / make_dedup_key --------------------------------------


def test_event_id_is_deterministic_with_entropy() -> None:
    ts = datetime(2024, 1, 3, 12, 0, tzinfo=UTC)
    a = new_event_id(ts, entropy=b"0123456789")
    b = new_event_id(ts, entropy=b"0123456789")
    assert a == b
    assert len(a) == 26


def test_event_ids_are_time_ordered() -> None:
    early = new_event_id(datetime(2024, 1, 3, 12, 0, tzinfo=UTC), entropy=b"\x00" * 10)
    late = new_event_id(datetime(2024, 1, 3, 12, 1, tzinfo=UTC), entropy=b"\x00" * 10)
    assert early < late


def test_make_dedup_key_stable() -> None:
    assert make_dedup_key("signal", "2024-01-03", "SPY") == "signal:2024-01-03:SPY"
    assert make_dedup_key("alert") == "alert"


# ---- Append-only + dedup (T8) -------------------------------------------


def test_append_event_persists_and_reads_back(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()

    record = store.append_event(_event())
    assert record.id == 1

    events = store.list_events(run_id="run-2024-01-03")
    assert len(events) == 1
    assert events[0].event.dedup_key == "signal:2024-01-03:SPY"


def test_append_event_is_idempotent_on_dedup_key(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()

    first = store.append_event(_event())
    # A re-run of the pipeline resubmits the same fact with a fresh event_id.
    second = store.append_event(
        _event(event_id=new_event_id(entropy=b"9876543210"))
    )

    assert first.id == second.id
    assert len(store.list_events()) == 1


def test_append_event_is_idempotent_under_concurrency(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    events = [
        _event(event_id=new_event_id(entropy=index.to_bytes(10, "big")))
        for index in range(12)
    ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        records = list(pool.map(store.append_event, events))

    assert len({record.id for record in records}) == 1
    assert len(store.list_events()) == 1


def test_events_listed_in_event_id_order(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()

    late = _event(
        event_id=new_event_id(datetime(2024, 1, 3, 13, tzinfo=UTC), entropy=b"\x11" * 10),
        dedup_key="signal:late",
    )
    early = _event(
        event_id=new_event_id(datetime(2024, 1, 3, 11, tzinfo=UTC), entropy=b"\x00" * 10),
        dedup_key="signal:early",
    )
    store.append_event(late)
    store.append_event(early)

    ordered = [rec.event.dedup_key for rec in store.list_events()]
    assert ordered == ["signal:early", "signal:late"]


def test_causal_chain_walks_back_to_root(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()

    root = _event(
        kind="data_ingested",
        event_id=new_event_id(datetime(2024, 1, 3, 10, tzinfo=UTC), entropy=b"\x00" * 10),
        dedup_key="data_ingested:1",
    )
    mid = _event(
        kind="signal",
        event_id=new_event_id(datetime(2024, 1, 3, 11, tzinfo=UTC), entropy=b"\x01" * 10),
        dedup_key="signal:1",
        causation_id=root.event_id,
    )
    leaf = _event(
        kind="order",
        event_id=new_event_id(datetime(2024, 1, 3, 12, tzinfo=UTC), entropy=b"\x02" * 10),
        dedup_key="order:1",
        causation_id=mid.event_id,
    )
    for event in (root, mid, leaf):
        store.append_event(event)

    chain = store.causal_chain(leaf.event_id)
    assert [rec.event.kind for rec in chain] == ["data_ingested", "signal", "order"]


# ---- Run digest / Merkle root (07 §4) -----------------------------------


def test_empty_run_has_stable_digest(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    assert store.compute_run_digest("empty") == compute_merkle_root([])


def test_merkle_root_is_order_independent() -> None:
    a = _event(dedup_key="a", event_id="A" * 26)
    b = _event(dedup_key="b", event_id="B" * 26)
    assert compute_merkle_root([a, b]) == compute_merkle_root([b, a])


def test_record_and_get_run_digest_roundtrip(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    store.append_event(_event())

    recorded = store.record_run_digest("run-2024-01-03")
    fetched = store.get_run_digest("run-2024-01-03")
    assert fetched is not None
    assert fetched.digest == recorded.digest
    assert fetched.event_count == 1


def test_record_run_digest_is_idempotent(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    store.append_event(_event())

    first = store.record_run_digest("run-2024-01-03")
    second = store.record_run_digest("run-2024-01-03")
    assert first.digest == second.digest
    assert len(store.list_events()) == 1
