# WP0 Probe Findings

Status: implementation research notes, not part of `docs/`.

> Historical note: this file records the pre-v3.1a A-share/HK-era probe work.
> It is preserved for audit context only. Current v3.1a active probes are
> yfinance, Stooq, EDGAR, and US trading calendars; AkShare/Tushare/BaoStock and
> HKEXnews are not active implementation paths.

Probe date: 2026-07-05  
Branch: `feat/wp0-foundation`

## Environment

Created an isolated conda environment:

```powershell
D:\Anaconda3\Scripts\conda.exe create -y -n yquant-py311 python=3.11 pip
```

Installed Poetry inside that environment and installed project dependencies with
the optional datasource group:

```powershell
$env:PATH='D:\Anaconda3\envs\yquant-py311;D:\Anaconda3\envs\yquant-py311\Scripts;' + $env:PATH
$env:POETRY_VIRTUALENVS_CREATE='false'
poetry lock
poetry install --with datasource
```

Important installed versions observed from the lock/install step:

- Python: 3.11.15
- Poetry: 2.4.1
- AkShare: 1.18.64
- Tushare: 1.4.29
- BaoStock: 0.9.2 package; runtime reports `00.9.20`

## Latest Probe Command

```powershell
python -m yquant probe all --output-dir data/probes
```

The raw JSON evidence is written under `data/probes/` and is intentionally not
tracked by git.

## Summary

| Source | Status | Implementation Meaning |
|---|---|---|
| AkShare | partial | Useful for trade calendar, stock master fragments, announcement titles/links. Daily bar endpoint failed in this run with a remote disconnect. |
| Tushare | partial | Package imports. Real checks skipped because `YQUANT_TUSHARE_TOKEN` is not set. |
| BaoStock | passed | Login, trade calendar, stock list, and daily bars passed. Good candidate backup/source for daily bars. |

## AkShare Details

Successful:

- `tool_trade_date_hist_sina`: 8,797 rows, covers 1990-12-19 through 2026-12-31.
- Split stock master functions:
  - `stock_info_sh_name_code(symbol="主板A股")`: 1,699 rows.
  - `stock_info_sz_name_code(symbol="A股列表")`: 2,895 rows.
  - `stock_info_bj_name_code()`: 324 rows.
  - Combined count in this probe: 4,918 rows.
- `stock_notice_report(symbol="全部", date="20240102")`: 854 rows, fields are code/name/title/type/date/url.

Failed:

- `stock_zh_a_hist(symbol="600000", period="daily", start_date="20240101", end_date="20240115", adjust="qfq", timeout=15)` failed with `RemoteDisconnected`.

Notes:

- The all-in-one `stock_info_a_code_name()` is too slow/noisy for a smoke probe; split exchange functions are better.
- Announcement probe confirms title/link availability, not正文 availability. Current AkShare notice function does not satisfy AS-1正文 by itself.
- AkShare prints tqdm progress from internals; probe JSON remains clean, but CLI output is noisy.

## Tushare Details

Successful:

- `import tushare`.

Skipped:

- All Pro API checks because `YQUANT_TUSHARE_TOKEN` is unset.

Implementation impact:

- Tushare cannot be accepted or rejected yet. Need a token before AS-3 financial announce date and AS-4 delisted coverage can be evaluated.

## BaoStock Details

Successful:

- `login()`.
- `query_trade_dates(start_date="2024-01-01", end_date="2024-01-31")`: 31 calendar rows.
- `query_all_stock(day="2024-01-02")`: 5,638 rows, but includes indices; adapter must filter stock codes.
- `query_history_k_data_plus("sh.600000", fields=..., start_date="2024-01-01", end_date="2024-01-15", frequency="d", adjustflag="2")`: 10 daily rows.

Implementation impact:

- BaoStock looks stable for trade calendar and daily bars.
- It is not enough for announcements/news, so it should be a market-data backup, not the full primary source.
- Returned rows are stringly typed; adapter must normalize dates, decimals, bool-like fields, and stock/index filtering.

## Immediate Decisions

1. M1 should not assume AkShare daily bars are always available. Implement primary/backup routing from the start.
2. BaoStock should be the first concrete daily-bar adapter because it passed the current probe.
3. AkShare should be kept for announcements and broad metadata, but公告正文 remains unresolved.
4. Tushare token is needed before finalizing AS-3/AS-4. Until then, financial `announce_date` remains an unresolved assumption.
5. Probe execution must keep subprocess timeouts. External data APIs are not reliable enough to call without guardrails.
