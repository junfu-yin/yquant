"""QA panel: assemble P-metric verdicts into a dashboard-ready summary (06 §8).

The panel is the single artefact CI prints and the UI renders, so a green board
means the same thing everywhere. Pure and JSON-safe.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from yquant.qa.metrics import MetricResult


@dataclass(frozen=True)
class QaPanel:
    """A rollup of P-metric results with a single blocking verdict."""

    results: tuple[MetricResult, ...]

    @property
    def passed(self) -> bool:
        """True only when no blocking or S1 metric failed.

        S1 denotes an immediate action condition and cannot produce a green board.
        S2/info failures remain visible without blocking this aggregate gate.
        """

        return not any(r.severity in {"block", "S1"} and not r.passed for r in self.results)

    @property
    def failures(self) -> tuple[MetricResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "total": len(self.results),
            "failed": len(self.failures),
            "blocking_failures": [
                r.metric for r in self.failures if r.severity in {"block", "S1"}
            ],
            "metrics": [r.as_dict() for r in self.results],
        }

    def render_text(self) -> str:
        """A compact human-readable board for CLI / CI logs."""

        lines = ["P-metric panel:"]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{mark}] {r.metric} {r.name} ({r.severity})")
        verdict = "GREEN" if self.passed else "RED"
        lines.append(f"verdict: {verdict}")
        return "\n".join(lines)


def build_panel(results: Sequence[MetricResult]) -> QaPanel:
    """Assemble metric results into a panel, ordered by metric id (P1, P2, …)."""

    ordered = sorted(results, key=lambda r: (int(r.metric[1:]), r.metric))
    return QaPanel(results=tuple(ordered))
