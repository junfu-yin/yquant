"""Lightweight data manifest records for reproducible M1 reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from yquant.datasrc.bars import date_bounds, normalize_symbols


@dataclass(frozen=True)
class DataManifest:
    manifest_id: str
    dataset: str
    source: str
    symbols: tuple[str, ...]
    start: date
    end: date
    row_count: int
    content_hash: str
    storage_path: str
    created_at_utc: datetime

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        payload["created_at_utc"] = self.created_at_utc.isoformat()
        return payload

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> DataManifest:
        created_at = datetime.fromisoformat(str(payload["created_at_utc"]))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return cls(
            manifest_id=str(payload["manifest_id"]),
            dataset=str(payload["dataset"]),
            source=str(payload["source"]),
            symbols=tuple(str(symbol) for symbol in payload["symbols"]),
            start=date.fromisoformat(str(payload["start"])),
            end=date.fromisoformat(str(payload["end"])),
            row_count=int(payload["row_count"]),
            content_hash=str(payload["content_hash"]),
            storage_path=str(payload["storage_path"]),
            created_at_utc=created_at.astimezone(UTC),
        )


def dataframe_content_hash(frame: pd.DataFrame) -> str:
    """Hash a DataFrame after deterministic row/column ordering."""

    ordered = frame.copy()
    ordered = ordered.reindex(sorted(ordered.columns), axis=1)
    sort_columns = [column for column in ("symbol", "date", "source") if column in ordered.columns]
    if sort_columns:
        ordered = ordered.sort_values(sort_columns)
    else:
        ordered = ordered.sort_values(list(ordered.columns))
    payload = cast(
        str,
        ordered.to_json(
            orient="records",
            date_format="iso",
            double_precision=12,
            force_ascii=True,
        ),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    frame: pd.DataFrame,
    *,
    dataset: str,
    source: str,
    storage_path: str | Path,
    created_at_utc: datetime | None = None,
) -> DataManifest:
    """Build a content-addressed manifest for a persisted dataset slice."""

    if frame.empty:
        raise ValueError("cannot build a manifest for an empty frame")
    start, end = date_bounds(frame)
    content_hash = dataframe_content_hash(frame)
    symbols = tuple(normalize_symbols(str(symbol) for symbol in frame["symbol"].unique()))
    normalized_source = source.strip().lower()
    manifest_id = (
        f"{dataset}:{normalized_source}:{start.isoformat()}:{end.isoformat()}:"
        f"{content_hash[:16]}"
    )
    created_at = created_at_utc or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return DataManifest(
        manifest_id=manifest_id,
        dataset=dataset,
        source=normalized_source,
        symbols=symbols,
        start=start,
        end=end,
        row_count=int(len(frame)),
        content_hash=content_hash,
        storage_path=str(storage_path),
        created_at_utc=created_at.astimezone(UTC),
    )


def append_manifest(path: Path, manifest: DataManifest) -> None:
    """Append one JSONL manifest record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest.to_json_dict(), sort_keys=True) + "\n")


def read_manifests(path: Path) -> list[DataManifest]:
    """Read JSONL manifest records if the file exists."""

    if not path.exists():
        return []
    manifests: list[DataManifest] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                manifests.append(DataManifest.from_json_dict(json.loads(stripped)))
    return manifests
