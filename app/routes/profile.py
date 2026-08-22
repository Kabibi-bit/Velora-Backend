from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
 
from app.db import get_db
from app.models.db_models import Profile
 
router = APIRouter(prefix="/profile", tags=["profile"])
 
 
class SurveyIn(BaseModel):
    user_id: str
    northstar: str
    final_idea: str | None = None
    timeframe: str
    stage: str
    priorities: list[str]
    skills: str
    dealbreakers: str | None = None
    location_pref: str | None = None
    target_types: list[str]
    open_to_offers: bool = False
 
 
@router.post("")
def create_profile(payload: SurveyIn, db: Session = Depends(get_db)):
    """Creates a new profile snapshot and marks it current.
    Previous profile rows stay in the table - that history is what
    lets the chatbot later explain how a user's goals have changed.
    """
    db.query(Profile).filter(
        Profile.user_id == payload.user_id, Profile.is_current == True  # noqa: E712
    ).update({"is_current": False})
 
    new_profile = Profile(
        user_id=payload.user_id,
        northstar=payload.northstar,
        final_idea=payload.final_idea,
        timeframe=payload.timeframe,
        stage=payload.stage,
        priorities=payload.priorities,
        skills=payload.skills,
        dealbreakers=payload.dealbreakers,
        location_pref=payload.location_pref,
        target_types=payload.target_types,
        open_to_offers=payload.open_to_offers,
        is_current=True,
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
    return {"status": "created", "profile_id": str(new_profile.id)}
 
 
@router.post("/{user_id}/open-to-offers")
def set_open_to_offers(user_id: str, value: bool, db: Session = Depends(get_db)):
    """Lets a candidate opt in/out of being visible to paying businesses,
    without having to resubmit the whole survey.
    """
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    profile.open_to_offers = value
    db.commit()
    return {"status": "updated", "open_to_offers": value}
 
 
@router.get("/{user_id}")
def get_current_profile(user_id: str, db: Session = Depends(get_db)):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    return {
        "id": str(profile.id),
        "northstar": profile.northstar,
        "final_idea": profile.final_idea,
        "timeframe": profile.timeframe,
        "stage": profile.stage,
        "priorities": profile.priorities,
        "skills": profile.skills,
        "dealbreakers": profile.dealbreakers,
        "location_pref": profile.location_pref,
        "target_types": profile.target_types,
    }
 
 
@router.get("/{user_id}/history")
def get_profile_history(user_id: str, db: Session = Depends(get_db)):
    profiles = (
        db.query(Profile)
        .filter(Profile.user_id == user_id)
        .order_by(desc(Profile.created_at))
        .all()
    )
    return [
        {
            "id": str(p.id),
            "northstar": p.northstar,
            "is_current": p.is_current,
            "created_at": p.created_at.isoformat(),
        }
        for p in profiles
    ]
 
 
@router.get("/{user_id}/potential-score")
def get_potential_score(user_id: str, db: Session = Depends(get_db)):
    """Server-side version of the frontend's 'Career potential' gauge -
    same formula (roadmap progress + skill coverage + match quality),
    computed from real stored data instead of client-side localStorage,
    so the number is trustworthy even if someone inspects the API directly.
    """
    from app.models.db_models import RoadmapMilestone, MatchScore
    import re
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
 
    milestones = db.query(RoadmapMilestone).filter(RoadmapMilestone.user_id == user_id).all()
    roadmap_progress = round((1 / len(milestones)) * 100) if milestones else 0
 
    skill_tokens = re.findall(r"[a-z][a-z\-]{2,}", (profile.skills or "").lower())
    skill_strength = min(100, len(skill_tokens) * 8)
 
    recent_scores = (
        db.query(MatchScore.score_pct)
        .filter(MatchScore.user_id == user_id)
        .order_by(desc(MatchScore.created_at))
        .limit(10)
        .all()
    )
    match_quality = round(sum(s[0] for s in recent_scores) / len(recent_scores)) if recent_scores else 40
 
    potential = round((roadmap_progress * 0.3) + (skill_strength * 0.3) + (float(match_quality) * 0.4))
    return {
        "potential_score": min(100, potential),
        "roadmap_progress": roadmap_progress,
        "skill_strength": skill_strength,
        "match_quality": match_quality,
    }
 
