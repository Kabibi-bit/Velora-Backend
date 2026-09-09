"""Manual listing entry -- the honest stand-in for a real college/
fellowship data pipeline. There is no free, reliable public API for
college admissions or fellowship listings comparable to Adzuna for
jobs (most are paywalled, institution-gated, or require data-sharing
agreements). Rather than fake a data source, this route lets you add
real listings by hand for now, so the matching/roadmap/chatbot
features can be tested against real admissions/fellowship data you
enter yourself. A real pipeline here would mean either paying for a
data license or building partnerships with individual programs.
"""
import hashlib
 
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
 
from app.db import get_db
from app.models.db_models import Listing
 
router = APIRouter(prefix="/listings/manual", tags=["listings"])
 
 
class ManualListingIn(BaseModel):
    title: str
    org: str
    type: str  # "college" or "internship" typically, for this route
    location: str | None = None
    description: str | None = None
    tags: list[str] = []
    deadline: date | None = None
    apply_url: str
 
 
@router.post("")
def add_manual_listing(payload: ManualListingIn, db: Session = Depends(get_db)):
    if not payload.title.strip() or not payload.org.strip() or not payload.apply_url.strip():
        raise HTTPException(status_code=400, detail="title, org, and apply_url cannot be empty")
    # apply_url anchors this instead of title+org - a real, different
    # listing at the same org with the same title (plausible in
    # practice) would otherwise collide against the real, enforced
    # UNIQUE(source, external_id) constraint and fail with a raw,
    # unhandled database error instead of ever being added.
    external_id = "manual_" + hashlib.sha256(payload.apply_url.strip().encode()).hexdigest()[:16]
    listing = Listing(
        source="manual",
        external_id=external_id,
        title=payload.title,
        org=payload.org,
        type=payload.type,
        location=payload.location,
        description=payload.description,
        tags=payload.tags,
        deadline=payload.deadline,
        apply_url=payload.apply_url,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return {"status": "added", "listing_id": str(listing.id)}
 
