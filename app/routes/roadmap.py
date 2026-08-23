import os
import re
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile, Listing, RoadmapMilestone
from app.services.roadmap import generate_roadmap, explain_listing_against_roadmap
from app.services.matching import rank_listings
 
router = APIRouter(prefix="/roadmap", tags=["roadmap"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "timeframe": p.timeframe or "",
        "stage": p.stage or "",
        "priorities": p.priorities or [],
        "dealbreakers": p.dealbreakers or "",
        "target_types": p.target_types or [],
    }
 
 
def _compute_skill_gaps(db: Session, profile_dict: dict) -> list[str]:
    """Finds tags that show up often in this user's top real matches
    but aren't in their stated skills or goal - the same logic the
    frontend chart uses, now grounding the roadmap in real data
    instead of generic advice.
    """
    listings = db.query(Listing).all()
    if not listings:
        return []
    listing_dicts = [
        {"id": str(l.id), "type": l.type, "title": l.title, "org": l.org, "tags": l.tags or []}
        for l in listings
    ]
    ranked = rank_listings(listing_dicts, profile_dict, top_n=8)
 
    skill_tokens = re.findall(r"[a-z][a-z\-]{2,}", profile_dict.get("skills", "").lower())
    goal_tokens = re.findall(r"[a-z][a-z\-]{2,}", (profile_dict["northstar"] + " " + profile_dict.get("final_idea", "")).lower())
 
    freq = {}
    for listing in ranked:
        for tag in listing.get("tags", []):
            known = any(t in tag or tag in t for t in skill_tokens) or any(t in tag or tag in t for t in goal_tokens)
            if not known:
                freq[tag] = freq.get(tag, 0) + 1
    return [tag for tag, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:4]]
 
 
@router.post("/{user_id}")
def create_roadmap(user_id: str, db: Session = Depends(get_db)):
    """Generates a fresh, grounded roadmap for this user and stores it,
    replacing any previous one. Each milestone now includes concrete
    success criteria and a realistic timeframe, and is informed by
    real skill gaps pulled from this user's actual current matches.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    profile_dict = _profile_to_dict(profile)
    skill_gaps = _compute_skill_gaps(db, profile_dict)
    milestones = generate_roadmap(client, profile_dict, skill_gaps=skill_gaps)
 
    db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).delete()
    for m in milestones:
        db.add(RoadmapMilestone(
            user_id=user_id,
            title=m["title"],
            description=m["description"],
            success_criteria=m.get("success_criteria", ""),
            estimated_timeframe=m.get("estimated_timeframe", ""),
            first_action=m.get("first_action", ""),
            target_stage=m["stage"],
        ))
    db.commit()
    return {"status": "created", "milestones": milestones, "skill_gaps_used": skill_gaps}
 
 
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
            {
                "title": m.title,
                "description": m.description,
                "success_criteria": m.success_criteria,
                "estimated_timeframe": m.estimated_timeframe,
                "first_action": m.first_action,
                "stage": m.target_stage,
                "status": m.status,
            }
            for m in milestones
        ]
    }
 
 
@router.get("/{user_id}/explain/{listing_id}")
def explain_listing(user_id: str, listing_id: str, db: Session = Depends(get_db)):
    """Returns Claude's explanation of how one specific listing fits
    the user's stored roadmap.
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
 
    roadmap_dicts = [
        {"stage": m.target_stage, "title": m.title, "description": m.description, "success_criteria": m.success_criteria}
        for m in milestones
    ]
    listing_dict = {"title": listing.title, "org": listing.org, "type": listing.type, "tags": listing.tags or []}
 
    explanation = explain_listing_against_roadmap(client, listing_dict, roadmap_dicts, _profile_to_dict(profile))
    return {"listing": listing.title, "explanation": explanation}
 
