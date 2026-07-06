# Implementation Log

This log records implementation decisions and verification results. It is not a
product specification; `docs/03_yquant技术方案_v3.1_完整版.md` remains the
authoritative spec.

## 2026-07-06 - WP0a v3.1a Alignment

Baseline:
- Head commit before code alignment: `fc9d9dd`.
- Authoritative docs: v3.1a.
- Active branch: `feat/wp0-foundation`.
- Existing verification state: `pytest` and `ruff` pass; `mypy` fails with 8
  pre-existing type errors.

Why this pass exists:
- Recent commits already added WP0 probes, config, market rules, core strategy
  sketches, M8 risk controls, and M5 discipline logic.
- Those modules were built against an earlier US/HK or v3 draft context.
- v3.1a narrows execution to US stocks and US-listed ETFs, USD accounting, and
  explicit Overlay/icebox guardrails.

Scope for this pass:
- Fix the existing type-checking baseline.
- Move active config defaults toward v3.1a.
- Add pure guardrail logic for Overlay, 2x, 3x/inverse, icebox, and
  discretionary/meme-stock requests.
- Keep historical research notes intact unless they actively mislead runtime
  behavior.

Completed changes:
- Runtime defaults now use `America/New_York`, US-only execution markets, and
  Stooq as the active backup source.
- Risk config now exposes 75/15/10 budgets plus Overlay and 2x caps.
- Active probe CLI was narrowed to yfinance, Stooq, EDGAR, and US calendars.
- Added `yquant.discipline.overlay_guardrails` with tests for ADR-37 and the
  icebox/2x/3x/inverse rules.
- Fixed the pre-existing type errors in probes, proposal construction, strategy
  inference literals, and indicator typing.

Verification:
- `python -m pytest`: 83 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.

Remaining implementation debt:
- Some legacy US/HK-era modules and tests remain in the tree but are no longer
  on the active config/CLI path. They should be either deleted or moved behind
  an explicit legacy/icebox boundary in the next cleanup pass.

Non-goals:
- No full M1 data repository.
- No UI.
- No broker automation.
- No LLM production flow.
