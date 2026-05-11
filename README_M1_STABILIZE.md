# TJK Ganyan Bot — M1 Stabilize Patch

Changed files:
- `dashboard/yerli_engine.py`
- `dashboard/app.py`

What it fixes:
1. Telegram formatter no longer crashes when `value_horses[].edge` is `None`, `NaN`, or non-numeric.
2. `/api/yerli_kupon` cache now accepts both `datetime` and ISO string timestamps.
3. Scheduler now writes cache timestamp as `datetime`, not string.
4. Scheduler now sends a best-effort Telegram alert when the 11:00 pipeline crashes or when kupon generation succeeds but Telegram send fails.
5. Adds `/api/health/deep` with scheduler, jobs, cache, and last pipeline state.

Deploy verification:
- `python -m py_compile dashboard/app.py dashboard/yerli_engine.py`
- `GET /api/health` should return 200.
- `GET /api/health/deep` should return 200 and include `scheduler.jobs`.
- `GET /api/yerli_kupon` should no longer return HTML/500 because of cache timestamp type.
- `GET /api/yerli_kupon/telegram` should no longer crash because of `edge=None` in value horses.

Rollback:
- Revert these two files or apply the reverse patch: `git apply -R tjk_m1_stabilize.patch`
