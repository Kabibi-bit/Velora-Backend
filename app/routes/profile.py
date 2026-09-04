import re
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
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
    is_athlete: bool = False
    sport: str | None = None
    level: str | None = None
    career_direction: str | None = None
    achievements: str | None = None
 
    @field_validator("northstar")
    @classmethod
    def northstar_must_be_real(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("northstar cannot be empty - it's the single most important field, feeding every scoring factor, roadmap, and career suggestion in the app")
        return v.strip()
 
    @field_validator("target_types")
    @classmethod
    def target_types_must_have_one(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("target_types cannot be empty - a profile with no target types would never match any listing at all")
        return v
 
    @field_validator("sport")
    @classmethod
    def sport_required_if_athlete(cls, v: str | None, info) -> str | None:
        # Mirrors the frontend's own hard block: if is_athlete is set,
        # sport must genuinely be real, not empty - the same check
        # survey.html itself does before it ever lets isAthlete
        # through with an empty sport field.
        if info.data.get("is_athlete") and (not v or not v.strip()):
            raise ValueError("sport cannot be empty when is_athlete is true")
        return v.strip() if v else v
 
 
ATHLETIC_HIGH_CONFIDENCE_WORDS = {
    "soccer", "basketball", "football", "baseball", "softball", "volleyball",
    "tennis", "golf", "swimming", "diving", "wrestling", "gymnastics",
    "hockey", "lacrosse", "rowing", "rugby", "cycling", "fencing",
    "archery", "boxing", "judo", "taekwondo", "karate", "skiing",
    "snowboarding", "cheerleading", "badminton", "squash", "cricket",
    "climbing", "triathlon", "powerlifting", "weightlifting", "bowling",
    "athlete", "athletics", "varsity", "ncaa", "olympian", "olympics",
}
ATHLETIC_HIGH_CONFIDENCE_PHRASES = [
    "student athlete", "student-athlete", "track and field", "track & field",
    "cross country", "field hockey", "water polo", "table tennis",
    "martial arts", "figure skating", "ultimate frisbee",
    "division i", "division ii", "division iii", "division 1", "division 2", "division 3",
    "go pro", "play professionally", "play in college", "play at the college level",
]
ATHLETIC_WEAK_SIGNAL_WORDS = {
    "scholarship", "captain", "recruiting", "recruit", "combine", "tryout",
    "tryouts", "coach", "coaching", "training", "roster", "draft", "league",
}
 
 
def detect_athletic_traits(text: str) -> dict:
    """Mirrors the frontend's detectAthleticTraits exactly - same
    tiered signal sets, same word-boundary tokenization. Any single
    high-confidence word/phrase is enough alone; two or more weak,
    ambiguous signals together also count, since one ambiguous word
    ("scholarship") is too easily a false positive on its own, but
    paired with something else ("scholarship" + "coach") genuinely
    isn't a coincidence.
    """
    lower = (text or "").lower()
    tokens = re.findall(r"[a-z][a-z\-]{2,}", lower)
    token_set = set(tokens)
 
    matched_high = [w for w in ATHLETIC_HIGH_CONFIDENCE_WORDS if w in token_set]
    matched_high += [p for p in ATHLETIC_HIGH_CONFIDENCE_PHRASES if p in lower]
    matched_weak = [w for w in ATHLETIC_WEAK_SIGNAL_WORDS if w in token_set]
 
    detected = len(matched_high) > 0 or len(matched_weak) >= 2
    return {"detected": detected, "matched_high": matched_high, "matched_weak": matched_weak}
 
 
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
        is_athlete=payload.is_athlete,
        sport=payload.sport,
        level=payload.level,
        career_direction=payload.career_direction,
        achievements=payload.achievements,
        is_current=True,
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)
 
    response = {"status": "created", "profile_id": str(new_profile.id)}
    # A real, honest safeguard - not a silent override. Forcing
    # is_athlete=true here would leave sport/level genuinely null
    # (the frontend never collects them if the toggle was off), and
    # could be wrong anyway - mentioning "sports marketing" isn't the
    # same as being an athlete. Surfacing the discrepancy respects the
    # person's own stated choice while still catching a real gap a
    # direct API call could otherwise sneak past entirely.
    if not payload.is_athlete:
        detection = detect_athletic_traits(f"{payload.northstar} {payload.final_idea or ''}")
        if detection["detected"]:
            response["athletic_signals_detected"] = detection["matched_high"] + detection["matched_weak"]
    return response
 
 
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
        "is_athlete": profile.is_athlete,
        "sport": profile.sport,
        "level": profile.level,
        "career_direction": profile.career_direction,
        "achievements": profile.achievements,
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
    done_count = sum(1 for m in milestones if m.status == "done")
    roadmap_progress = round((done_count / len(milestones)) * 100) if milestones else 0
 
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
 
 
class AutoApplySettingsIn(BaseModel):
    enabled: bool
    threshold: int = 80
 
 
@router.post("/{user_id}/auto-apply-settings")
def set_auto_apply_settings(user_id: str, payload: AutoApplySettingsIn, db: Session = Depends(get_db)):
    """Turns Auto Apply mode on/off and sets the confidence threshold
    that determines what gets auto-drafted-and-queued during a scan,
    versus what only gets surfaced as a regular match.
    """
    if payload.threshold < 50 or payload.threshold > 97:
        # 97 is the real, hard ceiling every match score is capped at
        # (see max(35, min(97, ...)) in matching.py) - allowing up to
        # 100 here meant a threshold could be set that no real match
        # could ever reach, silently disabling Auto Apply entirely.
        raise HTTPException(status_code=400, detail="threshold must be between 50 and 97 - 97 is the real ceiling every match score is capped at, so anything higher could never be reached by a real match")
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    profile.auto_apply_enabled = payload.enabled
    profile.auto_apply_threshold = payload.threshold
    db.commit()
    return {"status": "updated", "enabled": profile.auto_apply_enabled, "threshold": profile.auto_apply_threshold}
 
 
@router.get("/{user_id}/auto-apply-settings")
def get_auto_apply_settings(user_id: str, db: Session = Depends(get_db)):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    return {"enabled": profile.auto_apply_enabled, "threshold": profile.auto_apply_threshold}
 
