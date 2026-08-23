import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import SavedListing, Listing
from app.services.auto_apply import create_application_for_match
 
router = APIRouter(prefix="/saved", tags=["saved"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class SaveIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("")
def save_listing(payload: SaveIn, db: Session = Depends(get_db)):
    """Stars a listing - this is what backs the frontend's star icon
    and Saved panel. Starring ALSO automatically drafts a tailored
    application for that match (via create_application_for_match),
    landing in the Workshop page for review/approval/send. If the
    draft fails for any reason (no profile yet, a deal-breaker
    conflict, an AI call failure), the star itself still succeeds -
    drafting failures never block the save.
    """
    existing = (
        db.query(SavedListing)
        .filter(SavedListing.user_id == payload.user_id, SavedListing.listing_id == payload.listing_id)
        .first()
    )
    if existing:
        return {"status": "already saved"}
 
    saved = SavedListing(user_id=payload.user_id, listing_id=payload.listing_id)
    db.add(saved)
    db.commit()
 
    draft_result = None
    try:
        draft_result = create_application_for_match(db, client, payload.user_id, payload.listing_id)
        if draft_result.get("error"):
            draft_result = None  # profile missing, dealbreaker conflict, etc. - just skip silently
    except Exception:
        draft_result = None  # an AI/network failure should never break the save itself
 
    return {
        "status": "saved",
        "application_drafted": draft_result is not None and not draft_result.get("already_existed"),
        "application_id": draft_result.get("application_id") if draft_result else None,
    }
 
 
@router.delete("/{user_id}/{listing_id}")
def unsave_listing(user_id: str, listing_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(SavedListing)
        .filter(SavedListing.user_id == user_id, SavedListing.listing_id == listing_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not currently saved")
    db.delete(row)
    db.commit()
    return {"status": "unsaved"}
 
 
@router.get("/{user_id}")
def get_saved(user_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(SavedListing, Listing)
        .join(Listing, SavedListing.listing_id == Listing.id)
        .filter(SavedListing.user_id == user_id)
        .all()
    )
    return [
        {"listing_id": str(l.id), "title": l.title, "org": l.org, "type": l.type, "deadline": l.deadline.isoformat() if l.deadline else None}
        for _, l in rows
    ]
