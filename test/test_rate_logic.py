"""
Permanent logic tests for app/services/rate_limit.py.
 
The rate limiter is new code that protects against API-bill abuse. It must:
 - allow the first N uses, block the (N+1)th with HTTP 429,
 - keep per-user and per-action counts independent,
 - and CRITICALLY fail OPEN (never block a request) if its own DB errors.
 
Runs with no real DB - a tiny fake Session mimics the upsert-and-increment.
Stubs fastapi/sqlalchemy so the module imports without those installed.
 
    pytest tests/test_rate_limit_logic.py -v
    python3 tests/test_rate_limit_logic.py
"""
import importlib.util
import os
import sys
import types
 
# Stub the two external imports rate_limit.py makes at module load.
if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")
    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
    fastapi_stub.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi_stub
if "sqlalchemy" not in sys.modules:
    sqla = types.ModuleType("sqlalchemy")
    sqla.text = lambda s: s
    sys.modules["sqlalchemy"] = sqla
    orm = types.ModuleType("sqlalchemy.orm")
    class Session: pass
    orm.Session = Session
    sys.modules["sqlalchemy.orm"] = orm
 
from fastapi import HTTPException  # noqa: E402  (our stub)
 
_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "rate_limit", os.path.join(os.path.dirname(_here), "app", "services", "rate_limit.py"))
RL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RL)
 
 
class _FakeResult:
    def __init__(self, val): self._val = val
    def fetchone(self): return (self._val,) if self._val is not None else None
 
class FakeDB:
    """Mimics the atomic upsert-and-increment and the SELECT read."""
    def __init__(self): self.counts = {}
    def execute(self, stmt, params):
        s = str(stmt)
        if "INSERT INTO user_rate_limits" in s:
            k = (params["uid"], params["action"], params["d"])
            self.counts[k] = self.counts.get(k, 0) + 1
            return _FakeResult(self.counts[k])
        if "SELECT call_count" in s:
            k = (params["uid"], params["action"], params["d"])
            return _FakeResult(self.counts.get(k))
        return _FakeResult(None)
    def commit(self): pass
    def rollback(self): pass
 
class BrokenDB:
    def execute(self, *a, **k): raise RuntimeError("db down")
    def commit(self): pass
    def rollback(self): pass
 
 
def test_allows_up_to_limit_then_blocks():
    db = FakeDB()
    ok = 0
    for _ in range(3):
        try:
            RL.rate_limit(db, "u1", "act", limit_per_day=3); ok += 1
        except HTTPException:
            pass
    assert ok == 3
    blocked = False
    try:
        RL.rate_limit(db, "u1", "act", limit_per_day=3)
    except HTTPException as e:
        blocked = (e.status_code == 429)
    assert blocked
 
def test_usage_today_tracks():
    db = FakeDB()
    for _ in range(2):
        RL.rate_limit(db, "u1", "act", limit_per_day=10)
    assert RL.usage_today(db, "u1", "act") == 2
 
def test_per_user_independent():
    db = FakeDB()
    for _ in range(3):
        RL.rate_limit(db, "u1", "act", limit_per_day=3)
    # different user starts fresh
    RL.rate_limit(db, "u2", "act", limit_per_day=3)  # must not raise
 
def test_per_action_independent():
    db = FakeDB()
    for _ in range(3):
        RL.rate_limit(db, "u1", "actA", limit_per_day=3)
    RL.rate_limit(db, "u1", "actB", limit_per_day=3)  # must not raise
 
def test_fails_open_on_db_error():
    # A limiter malfunction must NEVER block the real request.
    RL.rate_limit(BrokenDB(), "u1", "act", limit_per_day=1)  # must not raise
    assert RL.usage_today(BrokenDB(), "u1", "act") == 0
 
 
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0; failed = []
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed.append(fn.__name__); print(f"  FAIL  {fn.__name__}: {e!r}")
    print(f"\n{passed}/{len(fns)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
 
