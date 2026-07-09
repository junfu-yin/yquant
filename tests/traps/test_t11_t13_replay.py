"""T11 / T13 replay traps: an old manifest replays unchanged; digests stay honest.

T11 (07 §3): official macro revisions arrive as later-``asof`` rows. A replay
reading at a past instant must not see them, so a backtest anchored to an old
manifest reproduces byte-for-byte even after a backfill.

T13 (07 §4): the run digest recomputed from persisted events must match the
digest recorded at run close; any post-hoc mutation is caught.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from yquant.datasrc.repo import LocalDataRepo
from yquant.ledger import Event, LedgerStore, Provenance, new_event_id
from yquant.ledger.replay import replay_run


def _macro(series_id: str, values: tuple[float, ...], asof: datetime) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(values), freq="D").date
    return pd.DataFrame(
        {
            "series_id": series_id,
            "date": list(dates),
            "value": list(values),
            "source": "yfinance",
            "asof": asof,
        }
    )


def test_t11_macro_revision_does_not_leak_into_old_replay(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    # Original print, recorded 2024-01-04.
    repo.write_macro_series(
        _macro("BAMLH0A0HYM2", (3.10, 3.25), datetime(2024, 1, 4, tzinfo=UTC))
    )

    old_cutoff = datetime(2024, 1, 5, tzinfo=UTC)
    before = repo.get_macro_series_asof(
        ["BAMLH0A0HYM2"], date(2024, 1, 1), date(2024, 1, 31), old_cutoff
    )
    original_values = list(before["value"])

    # An official revision lands a week later with a NEW asof.
    repo.write_macro_series(
        _macro("BAMLH0A0HYM2", (3.15, 3.30), datetime(2024, 1, 12, tzinfo=UTC))
    )

    # Replaying at the OLD cutoff must reproduce the pre-revision values.
    replayed = repo.get_macro_series_asof(
        ["BAMLH0A0HYM2"], date(2024, 1, 1), date(2024, 1, 31), old_cutoff
    )
    assert list(replayed["value"]) == original_values == [3.10, 3.25]

    # Reading at the NEW cutoff surfaces the revision.
    revised = repo.get_macro_series_asof(
        ["BAMLH0A0HYM2"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        datetime(2024, 1, 15, tzinfo=UTC),
    )
    assert list(revised["value"]) == [3.15, 3.30]


def _event(*, dedup_key: str, minute: int) -> Event:
    moment = datetime(2024, 1, 3, 12, minute, tzinfo=UTC)
    return Event(
        event_id=new_event_id(moment, entropy=bytes([minute]) * 10),
        ts=moment,
        kind="signal",
        payload={"dedup": dedup_key},
        run_id="run-t13",
        dedup_key=dedup_key,
        provenance=Provenance(git_sha="g", config_hash="c", data_manifest_id="m"),
    )


def test_t13_strict_replay_matches_recorded_digest(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    store.append_event(_event(dedup_key="a", minute=0))
    store.append_event(_event(dedup_key="b", minute=1))
    store.record_run_digest("run-t13")

    result = replay_run(store, "run-t13")
    assert result.strict_ok
    assert result.recorded_digest == result.recomputed_digest
