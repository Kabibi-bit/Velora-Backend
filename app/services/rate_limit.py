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
 
 
# ---------------------------------------------------------------------------
# Tier-aware limiting: a SHARED daily AI budget that differs by plan.
# ---------------------------------------------------------------------------
# The per-action limits above are anti-abuse ceilings on a single feature. This
# adds the plan-level difference users actually feel: a total number of AI
# actions per DAY across ALL AI features - Free 15, Pro 100, Max effectively
# unlimited. Both checks apply; whichever is stricter wins. Same fail-open
# guarantee: a limiter malfunction never blocks the real request.
 
# The shared counter uses a single reserved action name so every AI endpoint
# draws from one daily bucket per user.
_TIER_BUDGET_ACTION = "_ai_daily_budget"
 
 
def rate_limit_by_tier(db: Session, user_id: str, action: str, per_action_limit: int = DEFAULT_DAILY_LIMIT) -> None:
    """Enforce BOTH a per-action ceiling and the user's tier-wide daily AI budget.
 
    - `per_action_limit`: max uses of THIS specific action per day (anti-abuse).
    - tier budget: max total AI actions per day across all features, from the
      user's plan (tiers.TIER_LIMITS). 'max' tier (>=1000) is treated as
      effectively unlimited and the shared budget is skipped.
 
    Call this at the top of any AI-backed endpoint instead of rate_limit().
    """
    # 1. Per-action ceiling (unchanged behaviour).
    rate_limit(db, user_id, action, limit_per_day=per_action_limit)
 
    # 2. Tier-wide shared daily budget.
    try:
        from app.services.tiers import daily_limit as _tier_daily_limit
        budget = _tier_daily_limit(user_id_tier(db, user_id))
    except Exception:
        return  # fail open: can't determine budget -> don't block
    if budget >= 1000:
        return  # effectively unlimited (Max); skip the shared cap
    # Count one against the shared bucket and block if over the tier budget.
    key_date = _today()
    try:
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
            {"uid": str(user_id), "action": _TIER_BUDGET_ACTION, "d": key_date},
        ).fetchone()
        db.commit()
    except Exception:
        db.rollback()
        return  # fail open
    count = row[0] if row else 0
    if count > budget:
        from app.services.tiers import tier_required_for  # noqa: F401 (kept for symmetry)
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've used your plan's {budget} AI actions for today. "
                "Upgrade your plan for a higher daily limit, or try again tomorrow."
            ),
        )
 
 
def user_id_tier(db: Session, user_id: str) -> str:
    """Small indirection so this module doesn't hard-depend on tiers at import
    time (avoids any import cycle). Reads the user's tier, defaulting to free."""
    try:
        from app.services.tiers import get_user_tier
        return get_user_tier(db, user_id)
    except Exception:
        return "free"
 
 
def ai_budget_used_today(db: Session, user_id: str) -> int:
    """How many AI actions the user has spent from today's shared budget."""
    return usage_today(db, user_id, _TIER_BUDGET_ACTION)
 
