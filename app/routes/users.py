from fastapi import APIRouter, Depends, HTTPException
from app.services.auth import require_auth_for_user
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import User
 
router = APIRouter(prefix="/users", tags=["users"])
 
VALID_ROLES = {"candidate"}
 
 
class UserIn(BaseModel):
    email: EmailStr
    role: str = "candidate"
 
 
@router.post("")
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    # NOTE: intentionally public and unauthenticated. This is a bare,
    # password-less user record used for demo/testing only; real
    # account creation goes through /auth/signup (which hashes a
    # password and issues a token). Kept public because there is no
    # token to check before an account exists.
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
 
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        return {"user_id": str(existing.id), "status": "already exists", "role": existing.role}
 
    user = User(email=payload.email, role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": str(user.id), "status": "created", "role": user.role}
 
 
@router.get("/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user.id), "email": user.email, "role": user.role}
 
 
# --- Subscription tier (no payment yet; set via this endpoint for testing) ---
from app.services.tiers import normalize_tier, get_user_tier, TIER_FEATURES  # noqa: E402
from pydantic import BaseModel as _BaseModel  # noqa: E402
 
 
class _SetTierIn(_BaseModel):
    tier: str
 
 
@router.get("/{user_id}/tier")
def get_tier(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The user's current tier, its feature flags, the overall daily AI budget,
    and per-feature usage-vs-cap for today - so the client (e.g. the Plan page)
    can show real usage honestly instead of guessing."""
    t = get_user_tier(db, user_id)
    from app.services.tiers import daily_limit, feature_daily_cap
    from app.services.rate_limit import ai_budget_used_today, usage_today
    cap = daily_limit(t)
    used = ai_budget_used_today(db, user_id)
    # Per-feature usage today, keyed by the labels the Plan page displays.
    # (display label -> the rate-limit action name it counts against)
    _feature_actions = {
        "roadmaps": "roadmap-generate",
        "essay reviews": "essay-polish",
        "match explanations": "deep-explain",
    }
    features_usage = {}
    for label, action in _feature_actions.items():
        fcap = feature_daily_cap(t, action)
        features_usage[label] = {
            "used_today": usage_today(db, user_id, action),
            "limit": fcap,
            "unlimited": fcap >= 1000,
        }
    return {
        "tier": t,
        "features": TIER_FEATURES[t],
        "ai_budget": {"used_today": used, "limit": cap, "unlimited": cap >= 1000},
        "feature_usage": features_usage,
    }
 
 
@router.post("/{user_id}/tier")
def set_tier(user_id: str, payload: _SetTierIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Set the user's tier. NO PAYMENT YET - this exists so tiers are testable.
    When billing is added, tier changes should flow from verified subscription
    events (a webhook), and this open setter should be removed or locked down."""
    from sqlalchemy import text
    t = normalize_tier(payload.tier)
    db.execute(text("UPDATE users SET tier = :t WHERE id = :uid"), {"t": t, "uid": str(user_id)})
    db.commit()
    return {"tier": t, "features": TIER_FEATURES[t]}
 
