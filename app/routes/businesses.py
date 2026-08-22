"""Business-facing 'first look' feature: businesses register, then
purchase early access to candidates who have opted in to being
discoverable (profiles.open_to_offers = true).
 
HONEST LIMITATION: there is no real payment processor wired in here.
payment_status starts as 'pending' and the /mark-paid endpoint is an
admin-only manual override for now. To actually charge a business's
card, you'd need to integrate a processor like Stripe: create a
Stripe account, add a Checkout Session call in purchase_access()
below, and have Stripe's webhook call a new endpoint here to flip
payment_status to 'paid' automatically instead of you doing it by
hand. That integration is a distinct, separate build step - this
gives you the real data model and access-gating logic to plug it into.
"""
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Business, CandidateAccessPurchase, Profile, BusinessHire
 
router = APIRouter(prefix="/businesses", tags=["businesses"])
 
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
 
TIER_PRICES = {
    "first_look_7d": 49.00,
    "first_look_30d": 149.00,
}
 
 
def _require_admin(x_admin_secret: str = Header(default="")):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access required (X-Admin-Secret header)")
 
 
class BusinessIn(BaseModel):
    company_name: str
    contact_email: EmailStr
 
 
@router.post("/register")
def register_business(payload: BusinessIn, db: Session = Depends(get_db)):
    existing = db.query(Business).filter(Business.contact_email == payload.contact_email).first()
    if existing:
        return {"status": "already registered", "business_id": str(existing.id)}
    business = Business(company_name=payload.company_name, contact_email=payload.contact_email)
    db.add(business)
    db.commit()
    db.refresh(business)
    return {"status": "registered", "business_id": str(business.id)}
 
 
class PurchaseIn(BaseModel):
    business_id: str
    access_tier: str  # "first_look_7d" or "first_look_30d"
 
 
@router.post("/purchase-access")
def purchase_access(payload: PurchaseIn, db: Session = Depends(get_db)):
    """Creates a PENDING purchase record. No money actually moves yet -
    see the module docstring. In a real integration, this is where
    you'd create a Stripe Checkout Session and return its URL instead.
    """
    if payload.access_tier not in TIER_PRICES:
        raise HTTPException(status_code=400, detail=f"access_tier must be one of {list(TIER_PRICES)}")
    business = db.query(Business).filter(Business.id == payload.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
 
    days = 7 if "7d" in payload.access_tier else 30
    purchase = CandidateAccessPurchase(
        business_id=payload.business_id,
        access_tier=payload.access_tier,
        price_paid=TIER_PRICES[payload.access_tier],
        payment_status="pending",
        expires_at=datetime.utcnow() + timedelta(days=days),
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return {
        "purchase_id": str(purchase.id),
        "amount_due": TIER_PRICES[payload.access_tier],
        "status": "pending",
        "note": "Real payment collection is not yet wired in. An admin must confirm payment via /mark-paid before candidate access unlocks.",
    }
 
 
@router.post("/purchases/{purchase_id}/mark-paid")
def mark_paid(purchase_id: str, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    """Admin-only manual override until real payment processing exists."""
    purchase = db.query(CandidateAccessPurchase).filter(CandidateAccessPurchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found")
    purchase.payment_status = "paid"
    db.commit()
    return {"status": "paid", "expires_at": purchase.expires_at.isoformat()}
 
 
@router.get("/{business_id}/candidates")
def get_candidates(business_id: str, db: Session = Depends(get_db)):
    """Returns opted-in candidates, ONLY if this business has an
    active, paid access purchase. Never exposes email or any contact
    info directly - only what's needed to gauge fit.
    """
    now = datetime.utcnow()
    active_purchase = (
        db.query(CandidateAccessPurchase)
        .filter(
            CandidateAccessPurchase.business_id == business_id,
            CandidateAccessPurchase.payment_status == "paid",
            CandidateAccessPurchase.expires_at > now,
        )
        .first()
    )
    if not active_purchase:
        raise HTTPException(status_code=402, detail="No active paid access. Purchase first-look access via /businesses/purchase-access.")
 
    candidates = (
        db.query(Profile)
        .filter(Profile.is_current == True, Profile.open_to_offers == True)  # noqa: E712
        .all()
    )
    return [
        {
            "northstar": c.northstar,
            "skills": c.skills,
            "stage": c.stage,
            "location_pref": c.location_pref,
            "timeframe": c.timeframe,
        }
        for c in candidates
    ]
 
 
VALID_HIRE_STATUSES = {"contacted", "interviewing", "hired", "passed"}
 
 
class HireLogIn(BaseModel):
    business_id: str
    status: str
 
 
@router.post("/hires")
def log_hire_status(payload: HireLogIn, db: Session = Depends(get_db)):
    """Records a real pipeline event (contacted a candidate, moved to
    interview, hired, or passed) - this is what backs the dashboard's
    hiring donut chart and monthly target chart with real data.
    """
    if payload.status not in VALID_HIRE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_HIRE_STATUSES}")
    hire = BusinessHire(business_id=payload.business_id, status=payload.status)
    db.add(hire)
    db.commit()
    return {"status": "logged", "hire_status": payload.status}
 
 
@router.get("/{business_id}/hires/stats")
def get_hire_stats(business_id: str, db: Session = Depends(get_db)):
    rows = db.query(BusinessHire).filter(BusinessHire.business_id == business_id).all()
    by_status = {}
    by_month = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        month_key = r.created_at.strftime("%b")
        by_month[month_key] = by_month.get(month_key, 0) + 1
    return {"total": len(rows), "by_status": by_status, "by_month": by_month}
 
 
@router.get("/{business_id}/pipeline-score")
def get_pipeline_score(business_id: str, db: Session = Depends(get_db)):
    """Server-side version of the frontend's 'Pipeline strength' gauge -
    same formula (active access + candidate pool size + hire rate).
    """
    from datetime import datetime
 
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
 
    now = datetime.utcnow()
    active = (
        db.query(CandidateAccessPurchase)
        .filter(
            CandidateAccessPurchase.business_id == business_id,
            CandidateAccessPurchase.payment_status == "paid",
            CandidateAccessPurchase.expires_at > now,
        )
        .first()
        is not None
    )
    candidate_pool = db.query(Profile).filter(Profile.is_current == True, Profile.open_to_offers == True).count()  # noqa: E712
 
    hires = db.query(BusinessHire).filter(BusinessHire.business_id == business_id).all()
    hire_count = len([h for h in hires if h.status == "hired"])
    hire_rate = round((hire_count / len(hires)) * 100) if hires else 0
 
    pipeline_score = round((40 if active else 10) + min(30, candidate_pool * 7) + (hire_rate * 0.3))
    return {
        "pipeline_score": min(100, pipeline_score),
        "access_active": active,
        "candidate_pool_size": candidate_pool,
        "hire_rate": hire_rate,
    }
 
