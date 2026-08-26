import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Application
from app.services.auto_apply import (
    draft_application,
    decide_auto_send,
    compute_sendable_at,
    create_application_for_match,
)
 
router = APIRouter(prefix="/applications", tags=["applications"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class AcceptIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/accept")
def accept_match(payload: AcceptIn, db: Session = Depends(get_db)):
    """The one-click 'I accept this match' action - this is also what
    fires automatically when a user stars a listing (see /saved in
    saved_listings.py). Computes the real match score, drafts a
    tailored application via Claude, and decides whether it's
    confident enough to queue for auto-send or needs human review.
    """
    result = create_application_for_match(db, client, payload.user_id, payload.listing_id)
 
    if result.get("error") == "no_profile":
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if result.get("error") == "listing_not_found":
        raise HTTPException(status_code=404, detail="Listing not found")
    if result.get("error") == "dealbreaker_conflict":
        raise HTTPException(status_code=400, detail="This listing conflicts with one of your stated deal-breakers - not drafting an application for it.")
 
    if result.get("already_existed"):
        result["note"] = "An application for this match already exists - returning it instead of drafting a duplicate."
    else:
        result["note"] = "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first"
    return result
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
    confidence_pct: float
 
 
@router.post("/draft")
def create_draft(payload: DraftIn, db: Session = Depends(get_db)):
    """Drafts an application and decides auto-send vs review, based on
    the confidence score you pass in (use the score from /listings/matches).
    Kept for manual/testing use - /accept is the real one-click path.
    """
    from app.models.db_models import Profile, Listing
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == payload.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
    listing_dict = {"title": listing.title, "org": listing.org}
    draft_text = draft_application(client, listing_dict, profile_dict)
    status = decide_auto_send(payload.confidence_pct)
 
    app_record = Application(
        user_id=payload.user_id,
        listing_id=payload.listing_id,
        draft_content=draft_text,
        confidence_pct=payload.confidence_pct,
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "status": status,
        "draft": draft_text,
        "note": "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first",
    }
 
 
@router.get("/{user_id}")
def list_applications(user_id: str, db: Session = Depends(get_db)):
    """Lists all drafted applications for a user - this is what backs
    the frontend's Workshop page.
    """
    from app.models.db_models import Listing
 
    rows = (
        db.query(Application, Listing)
        .join(Listing, Application.listing_id == Listing.id)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(a.id),
            "listing_id": str(a.listing_id),
            "listing_title": l.title,
            "listing_org": l.org,
            "status": a.status,
            "confidence_pct": float(a.confidence_pct) if a.confidence_pct else None,
            "draft": a.draft_content,
            "sendable_at": a.sendable_at.isoformat() if a.sendable_at else None,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            "auto_generated": a.auto_generated,
            "created_at": a.created_at.isoformat(),
        }
        for a, l in rows
    ]
 
 
@router.post("/{application_id}/approve")
def approve_application(application_id: str, db: Session = Depends(get_db)):
    """For applications sitting in pending_review - the human approval step."""
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    app_record.status = "approved"
    app_record.sendable_at = compute_sendable_at()
    db.commit()
    return {"status": "approved", "sendable_at": app_record.sendable_at.isoformat()}
 
 
@router.post("/{application_id}/send")
def send_application(application_id: str, db: Session = Depends(get_db)):
    """Marks an application as sent, only if approved and the undo
    window has passed. NOTE: this does not submit anything to a real
    job site -- see the honest limitation noted in auto_apply.py.
    """
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    if app_record.status != "approved":
        raise HTTPException(status_code=400, detail="Application is not approved yet")
    if app_record.sendable_at and datetime.utcnow() < app_record.sendable_at:
        remaining = (app_record.sendable_at - datetime.utcnow()).seconds // 60
        raise HTTPException(status_code=400, detail=f"Still in undo window - {remaining} minutes left")
 
    app_record.status = "sent"
    app_record.sent_at = datetime.utcnow()
    db.commit()
    return {"status": "sent", "sent_at": app_record.sent_at.isoformat()}
 
 
@router.post("/{application_id}/undo")
def undo_application(application_id: str, db: Session = Depends(get_db)):
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    if app_record.status == "sent":
        raise HTTPException(status_code=400, detail="Already sent, cannot undo")
    app_record.status = "undone"
    db.commit()
    return {"status": "undone"}
 
 
@router.get("/{application_id}/explain-outcome")
def explain_outcome(application_id: str, db: Session = Depends(get_db)):
    """The rejection/ghost autopsy - a real, specific comparison of what
    was actually sent against the actual listing, grounded in the real
    outcome logged for it. Requires an outcome to already be logged via
    POST /outcomes for this listing, since there's nothing to analyze
    against otherwise.
    """
    import os
    import anthropic
    from app.models.db_models import Listing, Profile, Outcome
    from app.services.calibration import explain_outcome_deep
 
    app_record = db.query(Application).filter(Application.id == application_id).first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
 
    outcome = (
        db.query(Outcome)
        .filter(Outcome.user_id == app_record.user_id, Outcome.listing_id == app_record.listing_id)
        .order_by(Outcome.updated_at.desc())
        .first()
    )
    if not outcome:
        raise HTTPException(status_code=400, detail="No outcome logged for this application yet - log one via POST /outcomes first")
    if outcome.status not in {"rejected", "ghosted"}:
        raise HTTPException(status_code=400, detail="Autopsy is only meaningful for a rejected or ghosted outcome")
 
    listing = db.query(Listing).filter(Listing.id == app_record.listing_id).first()
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == app_record.user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not listing or not profile:
        raise HTTPException(status_code=404, detail="Listing or profile not found")
 
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    listing_dict = {"title": listing.title, "org": listing.org, "tags": listing.tags or []}
    profile_dict = {"northstar": profile.northstar, "skills": profile.skills or ""}
 
    explanation = explain_outcome_deep(
        client, listing_dict, app_record.draft_content,
        float(app_record.confidence_pct or 0), outcome.status, profile_dict,
    )
    return {"application_id": application_id, "outcome_status": outcome.status, "explanation": explanation}
 
