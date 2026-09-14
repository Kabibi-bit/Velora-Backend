"""Subscription tiers — the BACKEND source of truth for what Free / Pro / Max grant.
 
Why this exists: gating was frontend-only, which means a Free user was merely
*shown* a locked overlay - the underlying endpoint still ran for anyone with a
token. That makes the tier difference cosmetic, not real. This module lets the
backend actually ENFORCE the tiers, so a paid feature genuinely can't be used
without the tier, regardless of what the client does.
 
Kept deliberately in sync with the frontend TIERS in velora/state.js. A drift
test guards that the feature flags match.
 
No payment yet: a user's tier lives in users.tier (default 'free') and is set
via a switch endpoint for testing. When billing is added, only the SOURCE of the
tier changes (to the verified subscription) - every enforcement point here keeps
working unchanged.
"""
from fastapi import HTTPException
 
TIER_ORDER = ["free", "pro", "max"]
 
# Feature flags per tier. MUST match velora/state.js TIERS[*].features.
TIER_FEATURES = {
    "free": {
        "opportunity_watch": True, "roadmap": True, "metis": True, "manual_drafting": True,
        "school_readiness": True,
        "deep_match_explanations": False,
        "outreach_drafting": False,
        "auto_mode": False,
        "priority_metis": False,
        "early_access": False,
    },
    "pro": {
        "opportunity_watch": True, "roadmap": True, "metis": True, "manual_drafting": True,
        "school_readiness": True,
        "deep_match_explanations": True,
        "outreach_drafting": True,
        "auto_mode": True,
        "priority_metis": False,
        "early_access": False,
    },
    "max": {
        "opportunity_watch": True, "roadmap": True, "metis": True, "manual_drafting": True,
        "school_readiness": True, "deep_match_explanations": True, "outreach_drafting": True,
        "auto_mode": True,
        "priority_metis": True,
        "early_access": True,
    },
}
 
# Daily AI-action caps per tier (used to tune the rate limiter per plan).
TIER_LIMITS = {
    "free": {"ai_actions_per_day": 15, "auto_drafts_per_day": 0},
    "pro": {"ai_actions_per_day": 100, "auto_drafts_per_day": 10},
    "max": {"ai_actions_per_day": 1000, "auto_drafts_per_day": 1000},
}
 
 
def normalize_tier(tier) -> str:
    """Coerce any stored/blank/invalid value to a valid tier. Defaults to free
    (fail-closed: an unknown tier gets the least, never the most)."""
    t = (tier or "").strip().lower()
    return t if t in TIER_FEATURES else "free"
 
 
def tier_has_feature(tier, feature_key: str) -> bool:
    """True if `tier` includes `feature_key`. Unknown feature -> False
    (fail-closed: a missing flag hides a paid feature, never exposes it)."""
    feats = TIER_FEATURES[normalize_tier(tier)]
    return bool(feats.get(feature_key, False))
 
 
def tier_required_for(feature_key: str):
    """The lowest tier that grants a feature (for upgrade messaging)."""
    for t in TIER_ORDER:
        if TIER_FEATURES[t].get(feature_key):
            return t
    return None
 
 
def daily_limit(tier, key: str = "ai_actions_per_day") -> int:
    return TIER_LIMITS[normalize_tier(tier)].get(key, 0)
 
 
def get_user_tier(db, user_id: str) -> str:
    """Read a user's tier from the DB. Fails closed to 'free' on any error or
    missing column, so enforcement never breaks the app but also never
    accidentally grants a paid tier."""
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT tier FROM users WHERE id = :uid"), {"uid": str(user_id)}
        ).fetchone()
        return normalize_tier(row[0]) if row else "free"
    except Exception:
        return "free"
 
 
def require_feature(db, user_id: str, feature_key: str) -> None:
    """Raise HTTP 403 if the user's tier does not include `feature_key`. This is
    the real enforcement: call it at the top of any paid endpoint. The 403 names
    the tier needed, so the client can prompt an upgrade honestly."""
    if tier_has_feature(get_user_tier(db, user_id), feature_key):
        return
    needed = tier_required_for(feature_key)
    needed_name = {"pro": "Pro", "max": "Max"}.get(needed, "a paid plan")
    raise HTTPException(
        status_code=403,
        detail=f"This feature requires {needed_name}. Upgrade to unlock it.",
    )
 
