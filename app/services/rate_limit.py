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
    """Enforce a PER-FEATURE daily cap that scales by tier, plus a tier-wide
    daily AI budget backstop.
 
    - per-feature cap: from tiers.feature_daily_cap(tier, action) - e.g. a Free
      user gets 3 roadmaps/day, Pro 25, Max unlimited. This is the primary,
      prudent limit and it differs by plan.
    - `per_action_limit`: an optional absolute hard ceiling (anti-abuse), applied
      in addition; whichever is stricter wins.
    - tier budget: overall cap across ALL features (a backstop for abnormal use).
 
    Call this at the top of any AI-backed endpoint. Fails OPEN on any internal
    error so a limiter fault never breaks the feature.
    """
    tier = user_id_tier(db, user_id)
 
    # 1. Per-feature, per-tier cap (primary). 1000+ == effectively unlimited.
    try:
        from app.services.tiers import feature_daily_cap
        feat_cap = feature_daily_cap(tier, action)
    except Exception:
        feat_cap = None
    if feat_cap is not None and feat_cap < 1000:
        # the stricter of the tier's feature cap and any absolute ceiling
        effective = min(feat_cap, per_action_limit) if per_action_limit else feat_cap
        rate_limit(db, user_id, action, limit_per_day=effective)
    elif feat_cap is None:
        # unknown feature: fall back to the passed ceiling
        rate_limit(db, user_id, action, limit_per_day=per_action_limit)
    # (feat_cap >= 1000 -> unlimited for this feature at this tier; no per-action cap)
 
    # 2. Tier-wide shared daily budget backstop.
    try:
        from app.services.tiers import daily_limit as _tier_daily_limit
        budget = _tier_daily_limit(tier)
    except Exception:
        return  # fail open
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
 
