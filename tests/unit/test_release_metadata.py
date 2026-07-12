"""Release metadata stays aligned across the package and Poetry."""

from __future__ import annotations

import tomllib
from pathlib import Path

from yquant.version import EXECUTION_MODE, RELEASE_CHANNEL, __release_tag__, __version__


def test_alpha_release_metadata_is_explicit() -> None:
    assert __version__ == "0.1.0a1"
    assert __release_tag__ == "v0.1.0-alpha.1"
    assert RELEASE_CHANNEL == "alpha"
    assert EXECUTION_MODE == "shadow-only"


def test_poetry_and_runtime_versions_match() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    assert pyproject["tool"]["poetry"]["version"] == __version__
