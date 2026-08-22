import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile, Listing, Application
from app.services.auto_apply import draft_application, decide_auto_send, compute_sendable_at
from app.services.matching import score_listing
 
router = APIRouter(prefix="/applications", tags=["applications"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class AcceptIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("/accept")
def accept_match(payload: AcceptIn, db: Session = Depends(get_db)):
    """The one-click 'I accept this match' action: computes the real
    match score for this listing against the user's current profile,
    drafts a tailored application email via Claude, and automatically
    decides whether it's confident enough to queue for auto-send or
    needs human review first -- no confidence number needs to be
    passed in manually, unlike /applications/draft.
    """
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
 
    # Already have an application for this listing? Don't draft a duplicate.
    existing = (
        db.query(Application)
        .filter(Application.user_id == payload.user_id, Application.listing_id == payload.listing_id)
        .first()
    )
    if existing:
        return {
            "application_id": str(existing.id),
            "status": existing.status,
            "draft": existing.draft_content,
            "note": "An application for this match already exists - returning it instead of drafting a duplicate.",
        }
 
    profile_dict = {
        "northstar": profile.northstar,
        "final_idea": profile.final_idea or "",
        "skills": profile.skills or "",
        "dealbreakers": profile.dealbreakers or "",
        "priorities": profile.priorities or [],
    }
    listing_dict = {
        "type": listing.type,
        "tags": listing.tags or [],
        "title": listing.title,
        "org": listing.org,
    }
 
    match = score_listing(listing_dict, profile_dict)
    if match is None:
        raise HTTPException(status_code=400, detail="This listing conflicts with one of your stated deal-breakers - not drafting an application for it.")
 
    draft_text = draft_application(client, listing_dict, profile_dict)
    status = decide_auto_send(match["score_pct"])
 
    app_record = Application(
        user_id=payload.user_id,
        listing_id=payload.listing_id,
        draft_content=draft_text,
        confidence_pct=match["score_pct"],
        status=status,
        sendable_at=compute_sendable_at() if status == "approved" else None,
    )
    db.add(app_record)
    db.commit()
    db.refresh(app_record)
 
    return {
        "application_id": str(app_record.id),
        "match_score": match["score_pct"],
        "status": status,
        "draft": draft_text,
        "note": "approved = eligible to auto-send after the undo window; pending_review = needs your explicit approval first",
    }
 
 
class DraftIn(BaseModel):
    user_id: str
    listing_id: str
    confidence_pct: float
 
 
@router.post("/draft")
def create_draft(payload: DraftIn, db: Session = Depends(get_db)):
    """Drafts an application and decides auto-send vs review, based on
    the confidence score you pass in (use the score from /listings/matches).
    """
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
    rows = db.query(Application).filter(Application.user_id == user_id).all()
    return [
        {
            "id": str(a.id),
            "listing_id": str(a.listing_id),
            "status": a.status,
            "confidence_pct": float(a.confidence_pct) if a.confidence_pct else None,
            "sendable_at": a.sendable_at.isoformat() if a.sendable_at else None,
            "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        }
        for a in rows
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
 
