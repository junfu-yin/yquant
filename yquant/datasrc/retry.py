"""Retry/backoff policy for flaky external data-source fetches.

Kept pure and deterministic: the sleep function and jitter source are injected,
so the policy is fully unit-testable without real delays. This is the discipline
layer that must exist *before* the scheduler runs fetches unattended.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from random import Random
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with optional jitter.

    ``max_attempts`` counts the first try, so ``max_attempts=1`` disables retry.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    backoff_factor: float = 2.0
    jitter_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be non-negative")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative")
        if self.backoff_factor < 1:
            raise ValueError("backoff_factor must be at least 1")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be non-negative")

    def base_delay_for_attempt(self, attempt: int) -> float:
        """Return the pre-jitter delay after a failed ``attempt`` (1-indexed)."""

        if attempt < 1:
            raise ValueError("attempt must be at least 1")
        delay = self.base_delay_seconds * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


def run_with_retry(
    func: Callable[[], T],
    policy: RetryPolicy,
    *,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    rng: Random | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call ``func`` with exponential backoff, re-raising the last error.

    ``on_retry(attempt, error, delay)`` is invoked before each backoff sleep so
    callers can record retry evidence.
    """

    jitter_rng = rng or Random()
    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except retry_on as error:
            last_error = error
            if attempt >= policy.max_attempts:
                break
            delay = policy.base_delay_for_attempt(attempt)
            if policy.jitter_seconds > 0:
                delay += jitter_rng.uniform(0.0, policy.jitter_seconds)
            if on_retry is not None:
                on_retry(attempt, error, delay)
            if delay > 0:
                sleep(delay)
    assert last_error is not None  # loop only breaks after catching an error
    raise last_error
