from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile, Listing, MatchScore, Outcome, RoadmapMilestone
from app.services.matching import rank_listings, get_tag_weights_from_outcomes
 
router = APIRouter(prefix="/listings", tags=["listings"])
 
 
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
 
 
def _compute_roadmap_alignment(listing: dict, milestones: list) -> dict | None:
    """Fast, free, deterministic alignment between a listing and the
    user's roadmap - tag overlap against each milestone's title and
    description. This runs for every match, not just a handful,
    unlike the old approach which called Claude live per-listing and
    silently capped at 5. The deep, AI-written explanation is still
    available on demand via GET /roadmap/{user_id}/explain/{listing_id} -
    this heuristic is what makes every match show *some* grounded
    roadmap context immediately, for free.
    """
    if not milestones:
        return None
    listing_tags = set(t.lower() for t in listing.get("tags", []))
    best_stage, best_overlap = None, 0
    for m in milestones:
        milestone_text = (m["title"] + " " + m["description"]).lower()
        overlap = sum(1 for tag in listing_tags if tag in milestone_text)
        if overlap > best_overlap:
            best_overlap = overlap
            best_stage = m
    if not best_stage or best_overlap == 0:
        return None
    return {"stage": best_stage["stage"], "title": best_stage["title"], "matched_on": best_overlap}
 
 
@router.get("/matches/{user_id}")
def get_matches(user_id: str, db: Session = Depends(get_db)):
    """Returns the current top-ranked listings for a user, scored live
    against whatever's currently in the listings table. Every match
    includes a roadmap_alignment field (free, instant) showing which
    stage of the user's plan it advances, if any.
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
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    milestone_dicts = [{"stage": m.target_stage, "title": m.title, "description": m.description} for m in milestones]
    for listing in ranked:
        listing["roadmap_alignment"] = _compute_roadmap_alignment(listing, milestone_dicts)
 
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
 
