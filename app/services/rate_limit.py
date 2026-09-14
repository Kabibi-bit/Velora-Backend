"""Per-user rate limiting for expensive (AI-backed) endpoints.
 
Why this exists: 15 route files make paid Anthropic calls. Without a limit, a
single user (or a script with one stolen token) could loop those endpoints and
run up a large API bill or exhaust the quota and take the app down for everyone.
 
Design choices, made deliberately:
- **DB-backed, not in-memory.** An in-memory counter resets on every deploy and
  is wrong the moment there's more than one server instance (Render can run
  several). A tiny Postgres table gives a correct, shared, restart-proof count.
  It reuses the same pattern the codebase already uses for external-API quota.
- **Per authenticated user + per action, per rolling day.** Fairer than per-IP
  (which punishes shared networks like a school), and it maps to real cost.
- **Fails OPEN, not closed.** If the limiter itself errors (e.g. a transient DB
  hiccup), it lets the request through rather than breaking the product over a
  bookkeeping problem. A rate limiter should never be a new outage source.
 
Usage in a route:
 
    from app.services.rate_limit import rate_limit
 
    @router.post("/expensive-thing/{user_id}")
    def expensive(user_id: str, db: Session = Depends(get_db),
                  _auth: dict = Depends(require_auth_for_user)):
        rate_limit(db, user_id, "expensive-thing", limit_per_day=40)
        ...
"""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
 
 
# Sensible daily ceilings per action. Generous enough that a real student never
# notices, low enough that abuse is capped. Tune per endpoint as needed.
DEFAULT_DAILY_LIMIT = 50
 
 
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
 
 
def rate_limit(db: Session, user_id: str, action: str, limit_per_day: int = DEFAULT_DAILY_LIMIT) -> None:
    """Atomically count one use of `action` by `user_id` today and raise HTTP 429
    if it would exceed `limit_per_day`. Fails open on any internal error.
 
    Uses an upsert with a RETURNING clause so the read-and-increment is a single
    atomic statement (no race between concurrent requests double-spending).
    """
    key_date = _today()
    try:
        # Atomic upsert-and-increment; returns the new running count for today.
        row = db.execute(
            text(
                """
                INSERT INTO user_rate_limits (user_id, action, date, call_count)
                VALUES (:uid, :action, :d, 1)
                ON CONFLICT (user_id, action, date)
                DO UPDATE SET call_count = user_rate_limits.call_count + 1
                RETURNING call_count
                """
            ),
            {"uid": str(user_id), "action": action, "d": key_date},
        ).fetchone()
        db.commit()
    except Exception:
        # Fail OPEN: a limiter malfunction must never break the actual feature.
        db.rollback()
        return
 
    count = row[0] if row else 0
    if count > limit_per_day:
        # 429 = Too Many Requests. Include a clear, honest, non-alarming message.
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've reached today's limit for this feature ({limit_per_day} uses). "
                "This protects the service for everyone - please try again tomorrow."
            ),
        )
 
 
def usage_today(db: Session, user_id: str, action: str) -> int:
    """How many times `user_id` has used `action` today (0 if none/unknown).
    Read-only; fails open by returning 0."""
    try:
        row = db.execute(
            text(
                "SELECT call_count FROM user_rate_limits "
                "WHERE user_id = :uid AND action = :action AND date = :d"
            ),
            {"uid": str(user_id), "action": action, "d": _today()},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
 
