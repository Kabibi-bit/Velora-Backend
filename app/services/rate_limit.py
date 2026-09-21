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
 
 
# ---------------------------------------------------------------------------
# Login throttling: brute-force protection for the UNAUTHENTICATED /login route.
# ---------------------------------------------------------------------------
# The per-user limiters above key on an authenticated user_id, which login
# doesn't have yet. This throttles by BOTH the email being attempted and the
# client IP, on a rolling HOUR:
#   - per-email  -> caps online password-guessing against one specific account
#   - per-IP     -> caps one source spraying many accounts
# Only genuine FAILURES consume budget - a correct password never counts - so a
# real user is never throttled by their own successful logins, and a user who
# mistypes a few times is clear at the top of the next hour rather than locked
# out for a whole day. Reuses the existing user_rate_limits table (its columns
# are VARCHAR, so an email/IP key and an hour-stamped bucket fit with no schema
# change). Same DB-backed, multi-instance-correct, FAIL-OPEN design as above: a
# throttle malfunction must never lock everyone out of signing in.
LOGIN_MAX_FAILS_PER_EMAIL_PER_HOUR = 10
LOGIN_MAX_FAILS_PER_IP_PER_HOUR = 40
_LOGIN_FAIL_ACTION = "login_fail"
 
 
def _login_bucket() -> str:
    """Hour-granularity window key for the user_rate_limits.date column. A failed
    -attempt count naturally resets at the top of each UTC hour."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
 
 
def _login_keys(email: str, ip: str) -> tuple[str, str]:
    return ("login:email:" + (email or "").strip().lower(), "login:ip:" + ((ip or "").strip() or "unknown"))
 
 
def _rate_limit_count(db: Session, key: str, action: str, bucket: str) -> int:
    row = db.execute(
        text("SELECT call_count FROM user_rate_limits WHERE user_id = :k AND action = :a AND date = :d"),
        {"k": key, "a": action, "d": bucket},
    ).fetchone()
    return int(row[0]) if row else 0
 
 
def check_login_not_throttled(db: Session, email: str, ip: str) -> None:
    """Raise HTTP 429 if this email OR this client IP has already hit the
    failed-login ceiling for the current hour. READ-ONLY - it does not consume
    budget (only record_login_failure does), so it is safe to call on every
    attempt before verifying the password. Fails OPEN on any internal error."""
    bucket = _login_bucket()
    email_key, ip_key = _login_keys(email, ip)
    try:
        email_fails = _rate_limit_count(db, email_key, _LOGIN_FAIL_ACTION, bucket)
        ip_fails = _rate_limit_count(db, ip_key, _LOGIN_FAIL_ACTION, bucket)
    except Exception:
        return  # fail OPEN - a throttle read failure must never block real logins
    if email_fails >= LOGIN_MAX_FAILS_PER_EMAIL_PER_HOUR or ip_fails >= LOGIN_MAX_FAILS_PER_IP_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Please wait a few minutes and try again.",
        )
 
 
def record_login_failure(db: Session, email: str, ip: str) -> None:
    """Atomically count one FAILED login against BOTH the email and the IP for
    the current hour. Called only after a genuine credential failure - a
    successful login never calls this, so real users don't spend the budget.
    Each counter is its own atomic upsert; a failure on one still records the
    other, and any error fails OPEN (a bookkeeping fault must never turn a normal
    failed login into a 500)."""
    bucket = _login_bucket()
    for key in _login_keys(email, ip):
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_rate_limits (user_id, action, date, call_count)
                    VALUES (:k, :a, :d, 1)
                    ON CONFLICT (user_id, action, date)
                    DO UPDATE SET call_count = user_rate_limits.call_count + 1
                    """
                ),
                {"k": key, "a": _LOGIN_FAIL_ACTION, "d": bucket},
            )
            db.commit()
        except Exception:
            db.rollback()  # fail open; skip this one counter
 
