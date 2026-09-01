import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Outcome
 
router = APIRouter(prefix="/outcomes", tags=["outcomes"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
VALID_STATUSES = {"applied", "interview", "rejected", "ghosted", "offer"}
 
 
class OutcomeIn(BaseModel):
    user_id: str
    listing_id: str
    status: str
 
 
@router.post("")
def log_outcome(payload: OutcomeIn, db: Session = Depends(get_db)):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
    outcome = Outcome(user_id=payload.user_id, listing_id=payload.listing_id, status=payload.status)
    db.add(outcome)
    db.commit()
    return {"status": "logged", "outcome_status": payload.status}
 
 
@router.get("/{user_id}")
def get_outcomes(user_id: str, db: Session = Depends(get_db)):
    rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    return [{"listing_id": str(r.listing_id), "status": r.status, "updated_at": r.updated_at.isoformat()} for r in rows]
 
 
@router.get("/{user_id}/stats")
def get_outcome_stats(user_id: str, db: Session = Depends(get_db)):
    """Real aggregation backing the dashboard's donut chart and monthly
    target chart - counts by status, and counts by month for the last
    3 months, computed from actual logged outcomes (no mock numbers).
    """
    rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
 
    by_status = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
 
    by_month = {}
    for r in rows:
        month_key = r.updated_at.strftime("%b")
        by_month[month_key] = by_month.get(month_key, 0) + 1
 
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_month": by_month,
    }
 
 
@router.get("/{user_id}/calibration")
def get_calibration(user_id: str, db: Session = Depends(get_db)):
    """Is Velora's own confidence score actually trustworthy for THIS
    user? Joins real logged outcomes back to the confidence score each
    application had when sent, and reports the real conversion rate
    per confidence bucket. This is the honest, self-auditing feature -
    it will show unflattering numbers if the score isn't well
    calibrated for someone, rather than hiding that.
    """
    from app.models.db_models import Application
    from app.services.calibration import compute_calibration
 
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    applications = db.query(Application).filter(Application.user_id == user_id).all()
 
    outcome_dicts = [{"listing_id": str(o.listing_id), "status": o.status} for o in outcomes]
    app_dicts = [{"listing_id": str(a.listing_id), "confidence_pct": a.confidence_pct} for a in applications]
 
    calibration = compute_calibration(app_dicts, outcome_dicts)
    total_with_outcomes = sum(b["total_with_outcomes"] for b in calibration.values())
    return {
        "calibration": calibration,
        "total_applications_with_logged_outcomes": total_with_outcomes,
        "note": "Buckets with fewer than a handful of outcomes aren't statistically meaningful yet - log more real outcomes to sharpen this." if total_with_outcomes < 5 else None,
    }
 
 
@router.get("/{user_id}/personalization-audit")
def get_personalization_audit(user_id: str, db: Session = Depends(get_db)):
    """The self-audit no mainstream job platform does: checks whether
    Velora's OWN personalized scoring is actually helping THIS user,
    or just moving numbers around. Compares the real (personalized)
    score each application had against what it would have scored
    without personalization, restricted to cases where the two
    genuinely differed - then checks which version better tracked
    the real outcome. Will honestly report "hurting" if that's what
    the data shows.
    """
    from app.models.db_models import Application
    from app.services.matching import audit_personalization_effect
 
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    outcome_by_listing = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.counterfactual_confidence_pct.isnot(None))
        .all()
    )
    audit_input = [
        {
            "confidence_pct": float(a.confidence_pct),
            "counterfactual_confidence_pct": float(a.counterfactual_confidence_pct),
            "outcome_status": outcome_by_listing[str(a.listing_id)],
        }
        for a in applications
        if str(a.listing_id) in outcome_by_listing
    ]
    return audit_personalization_effect(audit_input)
 
 
@router.get("/{user_id}/personalization-insights")
def get_personalization_insights(user_id: str, db: Session = Depends(get_db)):
    """The genuine depth upgrade beyond factor-category reweighting -
    reads the real content of applications you actually sent, not
    just pre-computed numeric factor tallies, and finds specific,
    content-grounded patterns in what's actually worked. Complements
    /personalization-audit (which checks whether the numeric
    reweighting is helping) with something numbers alone can't give:
    real qualitative insight into what you've actually written.
    """
    from app.models.db_models import Application, Listing
    from app.services.matching import generate_deep_personalization_insights
 
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    outcome_by_listing = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at)
        # Without an explicit order, PostgreSQL returns rows in an
        # unspecified order that "must not be relied on" (per the
        # official docs) - meaning "Application 3" could genuinely
        # refer to a different real application between calls, which
        # would directly undermine the whole point of the model
        # referencing applications by number and the flagged_insight
        # check that verifies those references. Ordered by creation
        # time so the numbering is stable and chronologically sensible.
        .all()
    )
    app_input = [
        {
            "draft_content": a.draft_content,
            "listing_title": listing.title,
            "listing_org": listing.org,
            "listing_tags": listing.tags or [],
            "outcome_status": outcome_by_listing.get(str(a.listing_id)),
        }
        for a, listing in applications
    ]
    try:
        return generate_deep_personalization_insights(client, app_input)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate personalization insights just now: {e}")
 
 
@router.get("/{user_id}/factor-interactions")
def get_factor_interactions(user_id: str, db: Session = Depends(get_db)):
    """Goes beyond /personalization-audit and the numeric weights in
    /listings/matches: those can only ever say whether a SINGLE
    factor predicts success in isolation. This checks whether PAIRS
    of signals only work TOGETHER - e.g. real skill overlap might
    only actually predict success for this person when it's paired
    with genuine conceptual fit, and neither alone is enough. A real
    statistical concept (interaction effects) that even sophisticated
    platforms rarely expose transparently.
    """
    from app.models.db_models import Application
    from app.services.matching import compute_factor_interactions
 
    outcomes = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    outcome_by_listing_status = {str(o.listing_id): o.status for o in outcomes}
 
    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id, Application.factors_snapshot.isnot(None))
        .all()
    )
