"""AI brief generation modules (M4 individual-stock event cards, 03 §5.4)."""

from yquant.brief.eval import (
    EvalMetrics,
    EvalSample,
    build_eval_corpus,
    evaluate_corpus,
    run_eval,
)
from yquant.brief.filings import (
    EIGHT_K_ITEMS,
    Form4Filing,
    Form4Transaction,
    ItemSpec,
    classify_8k,
    left_truncate,
    parse_form4,
)
from yquant.brief.pipeline import (
    DEFAULT_MAX_INPUT_CHARS,
    EightKFiling,
    NumericVerificationError,
    build_8k_card,
    build_form4_card,
)
from yquant.brief.schemas import EventCard
from yquant.brief.verifier import (
    number_is_verified,
    verify_key_numbers,
)

__all__ = [
    "DEFAULT_MAX_INPUT_CHARS",
    "EIGHT_K_ITEMS",
    "EightKFiling",
    "EvalMetrics",
    "EvalSample",
    "EventCard",
    "Form4Filing",
    "Form4Transaction",
    "ItemSpec",
    "NumericVerificationError",
    "build_8k_card",
    "build_eval_corpus",
    "build_form4_card",
    "classify_8k",
    "evaluate_corpus",
    "left_truncate",
    "number_is_verified",
    "parse_form4",
    "run_eval",
    "verify_key_numbers",
]
