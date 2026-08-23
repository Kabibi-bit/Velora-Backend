from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile, Listing, MatchScore, Outcome, RoadmapMilestone
from app.services.matching import rank_listings, get_tag_weights_from_outcomes, compute_roadmap_alignment
 
router = APIRouter(prefix="/listings", tags=["listings"])
 
 
def _profile_to_dict(p: Profile) -> dict:
    return {
        "northstar": p.northstar,
        "final_idea": p.final_idea or "",
        "skills": p.skills or "",
        "dealbreakers": p.dealbreakers or "",
        "priorities": p.priorities or [],
        "target_types": p.target_types or [],
        "location_pref": p.location_pref or "",
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
        listing["roadmap_alignment"] = compute_roadmap_alignment(listing, milestone_dicts)
 
    return {"matches": ranked, "profile_id": str(profile.id), "outcomes_considered": len(outcome_dicts)}
 
 
@router.post("/scan/{user_id}")
async def trigger_scan(user_id: str, db: Session = Depends(get_db)):
    """Manually triggers an immediate scan: pulls fresh listings from
    Adzuna (if any are new), then re-scores everything for this user.
    If the user has Auto Apply mode enabled, this also automatically
    drafts and queues applications for every eligible match above
    their configured threshold - no manual starring required.
    """
    import os
    import anthropic
    from app.services.scheduler import run_scan_for_user, _pull_and_store_new_listings
    from app.services.auto_apply import create_application_for_match
 
    new_count = await _pull_and_store_new_listings(db)
    result = run_scan_for_user(db, user_id)
    result["new_listings_pulled"] = new_count
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    auto_applied = []
    if profile and profile.auto_apply_enabled:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        listings = db.query(Listing).all()
        ranked = rank_listings([_listing_to_dict(l) for l in listings], _profile_to_dict(profile), top_n=10)
        for listing in ranked:
            outcome = create_application_for_match(db, client, user_id, listing["id"], auto_generated=True)
            if not outcome.get("error") and not outcome.get("already_existed") and outcome.get("status") == "approved":
                auto_applied.append({"listing_id": listing["id"], "title": listing["title"], "confidence": outcome["composite_confidence"]})
    result["auto_applied"] = auto_applied
 
    return result
 
 
@router.get("/matches/{user_id}/explain/{listing_id}")
def explain_match_deep(user_id: str, listing_id: str, db: Session = Depends(get_db)):
    """On-demand DEEP explanation of why a listing is a good match -
    a real Claude call producing an actual paragraph grounded in the
    full profile, the listing, and the roadmap if one exists. This is
    separate from the free, instant explain_score() text that ships
    with every match by default - that one covers the same signals
    but as a quick multi-clause sentence. This endpoint is for when
    someone wants more depth than that, and is deliberately only
    called when asked for, not automatically for every listing in a
    scan (which would multiply your Anthropic usage by however many
    matches are returned, every cycle).
    """
    import os
    import anthropic
    from app.models.db_models import RoadmapMilestone
 
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    milestones = (
        db.query(RoadmapMilestone)
        .filter(RoadmapMilestone.user_id == user_id)
        .order_by(RoadmapMilestone.target_stage)
        .all()
    )
    roadmap_line = ""
    if milestones:
        roadmap_line = "Their roadmap:\n" + "\n".join(f"{m.target_stage}. {m.title}" for m in milestones) + "\n\n"
 
    prompt = (
        f"A candidate's goal: \"{profile.northstar}\". What 'made it' looks like: \"{profile.final_idea or ''}\". "
        f"Their skills: \"{profile.skills or ''}\". What matters most to them: {', '.join(profile.priorities or [])}. "
        f"Location preference: \"{profile.location_pref or ''}\".\n\n"
        f"{roadmap_line}"
        f"A listing they're considering: \"{listing.title}\" at {listing.org} ({listing.type}), "
        f"location {listing.location or 'unspecified'}, tags: {', '.join(listing.tags or [])}.\n\n"
        "Write a genuine, specific 3-4 sentence case for why this is or isn't a strong match for "
        "THIS candidate specifically - reference their actual goal, skills, priorities, and roadmap "
        "by name where relevant. Be honest about weak fit if it's weak, don't oversell. No generic "
        "filler like 'this could be a great opportunity' - every sentence should reference a specific "
        "fact about the candidate or the listing."
    )
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    explanation = "".join(b.text for b in resp.content if b.type == "text").strip()
    return {"listing_id": listing_id, "listing_title": listing.title, "explanation": explanation}
 
