import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile, Listing, RoadmapMilestone
from app.services.roadmap import generate_roadmap, explain_listing_against_roadmap
 
router = APIRouter(prefix="/roadmap", tags=["roadmap"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "timeframe": p.timeframe or "",
        "stage": p.stage or "",
    }
 
 
@router.post("/{user_id}")
def create_roadmap(user_id: str, db: Session = Depends(get_db)):
    """Generates a fresh roadmap for this user and stores it,
    replacing any previous one.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    milestones = generate_roadmap(client, _profile_to_dict(profile))
 
    db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).delete()
    for m in milestones:
        db.add(RoadmapMilestone(
            user_id=user_id,
            title=m["title"],
            description=m["description"],
            target_stage=m["stage"],
        ))
    db.commit()
    return {"status": "created", "milestones": milestones}
 
 
@router.get("/{user_id}")
def get_roadmap(user_id: str, db: Session = Depends(get_db)):
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        return {"milestones": [], "note": "No roadmap yet - POST to this URL to generate one."}
    return {
        "milestones": [
            {"title": m.title, "description": m.description, "stage": m.target_stage, "status": m.status}
            for m in milestones
        ]
    }
 
 
@router.get("/{user_id}/explain/{listing_id}")
def explain_listing(user_id: str, listing_id: str, db: Session = Depends(get_db)):
    """The actual 'why is this useful for my roadmap' feature you asked for -
    returns Claude's explanation of how one specific listing fits the
    user's stored roadmap.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if not milestones:
        raise HTTPException(status_code=404, detail="No roadmap yet - generate one first with POST /roadmap/{user_id}")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    roadmap_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
    listing_dict = {"title": listing.title, "org": listing.org, "type": listing.type, "tags": listing.tags or []}
 
    explanation = explain_listing_against_roadmap(client, listing_dict, roadmap_dicts, _profile_to_dict(profile))
    return {"listing": listing.title, "explanation": explanation}
 
