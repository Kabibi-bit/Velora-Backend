from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import SavedListing, Listing
 
router = APIRouter(prefix="/saved", tags=["saved"])
 
 
class SaveIn(BaseModel):
    user_id: str
    listing_id: str
 
 
@router.post("")
def save_listing(payload: SaveIn, db: Session = Depends(get_db)):
    """Stars a listing - this is what backs the frontend's star icon
    and Saved panel, which were previously only in browser localStorage.
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
    return {"status": "saved"}
 
 
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
 
