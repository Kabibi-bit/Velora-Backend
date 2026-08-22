import os
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile, Listing, MatchScore, Outcome, RoadmapMilestone
from app.services.matching import rank_listings, get_tag_weights_from_outcomes
from app.services.roadmap import explain_listing_against_roadmap
 
router = APIRouter(prefix="/listings", tags=["listings"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "dealbreakers": p.dealbreakers or "",
        "priorities": p.priorities or [],
        "target_types": p.target_types or [],
    }
 
 
def _listing_to_dict(l: Listing) -> dict:
    return {
        "id": str(l.id),
        "type": l.type,
        "title": l.title,
        "org": l.org,
        "tags": l.tags or [],
        "location": l.location,
        "deadline": l.deadline.isoformat() if l.deadline else None,
    }
 
 
@router.get("/matches/{user_id}")
def get_matches(user_id: str, db: Session = Depends(get_db)):
    """Returns the current top-ranked listings for a user, scored live
    against whatever's currently in the listings table.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listings = db.query(Listing).all()
    if not listings:
        return {"matches": [], "note": "No listings in the database yet - run a scan first."}
 
    # Pull this user's real outcome history and let it adjust scores -
    # this is the actual "self-correcting" piece: a heuristic, not
    # machine learning, but grounded in real recorded results.
    outcome_rows = db.query(Outcome).filter(Outcome.user_id == user_id).all()
    listings_by_id = {str(l.id): l for l in listings}
    outcome_dicts = []
    for o in outcome_rows:
        listing = listings_by_id.get(str(o.listing_id))
        if listing:
            outcome_dicts.append({"tags": listing.tags or [], "status": o.status})
    tag_weights = get_tag_weights_from_outcomes(outcome_dicts)
 
    ranked = rank_listings(
        [_listing_to_dict(l) for l in listings],
        _profile_to_dict(profile),
        top_n=10,
        tag_weights=tag_weights,
    )
 
    # If this user has a saved roadmap, ground the top matches' "why"
    # in it automatically - not just tag overlap, but which stage of
    # their actual plan this listing advances. Capped to the top 5
    # to keep the AI cost bounded; the rest still get the free
    # rule-based rationale that's already on every match.
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    if milestones:
        roadmap_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
        profile_dict = _profile_to_dict(profile)
        for listing in ranked[:5]:
            try:
                listing["roadmap_explanation"] = explain_listing_against_roadmap(
                    client, listing, roadmap_dicts, profile_dict
                )
            except Exception as e:
                listing["roadmap_explanation"] = None
                listing["roadmap_explanation_error"] = str(e)
 
    return {"matches": ranked, "profile_id": str(profile.id), "outcomes_considered": len(outcome_dicts)}
 
 
@router.post("/scan/{user_id}")
async def trigger_scan(user_id: str, db: Session = Depends(get_db)):
    """Manually triggers an immediate scan: pulls fresh listings from
    Adzuna (if any are new), then re-scores everything for this user.
    This is what actually populates the listings table on a manual
    trigger, rather than only scoring whatever's already there.
    """
    from app.services.scheduler import run_scan_for_user, _pull_and_store_new_listings
 
    new_count = await _pull_and_store_new_listings(db)
    result = run_scan_for_user(db, user_id)
    result["new_listings_pulled"] = new_count
    return result
 
