# Tests

Three layers, by what they need to run:

## 1. Pure-logic suite — run this on every change (seconds, no setup)

```bash
python3 tests/run_all.py          # runs everything below, one summary
# or individually:
python3 tests/test_schools_logic.py
python3 tests/test_rate_limit_logic.py
# or with pytest:
pytest tests/test_schools_logic.py tests/test_rate_limit_logic.py -v
```

Covers the admissions engine (29 pure functions: search, readiness,
list-balance, gap-radar, trajectory, essay tools) and the rate limiter. No
database, no network - imports the service modules directly. Every past bug is
locked in here as a regression test, so it can't silently return.

**This is the gate.** If `run_all.py` isn't green, don't ship.

## 2. DB-backed test — needs a real Postgres

```bash
pytest tests/test_personalization_audit.py -v
```
See the docstring in that file for the one-time Postgres setup. It uses a real,
disposable database (not SQLite) because the models use Postgres-specific types.

## 3. Live end-to-end — needs the deployed server + DB

```bash
export VELORA_API_BASE="https://your-host"
python3 scripts/verify_admissions_staging.py
```
Exercises all 15 /schools endpoints against a running server. This is the final
pre-launch check; it can't run in a sandbox. See ADMISSIONS_TEST_GUIDE.md.
