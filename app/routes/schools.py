from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.auth import require_auth_for_user
from app.services.schools import (
    search_schools,
    lookup_school,
    school_guidance_for_profile,
    generate_admissions_roadmap,
    essay_structure,
    admissions_deadline_context,
    admissions_assistant_context,
    admissions_readiness,
)
 
router = APIRouter(prefix="/schools", tags=["schools"])
 
 
def _load_student_profile(user_id: str, db: Session) -> dict:
    """Shared: validate the user_id, load the current profile, ensure it's on
    the admissions track, and return it as the plain dict the schools service
    expects. Raises the same HTTP errors every admissions route needs."""
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    if not profile.is_student:
        raise HTTPException(status_code=400, detail="This profile is not on the admissions track")
 
    return {
        "intended_major": profile.intended_major,
        "grade_level": profile.grade_level,
        "target_schools": profile.target_schools,
        "interests": profile.interests,
        "student_achievements": getattr(profile, "student_achievements", None),
    }
 
 
# ---------------------------------------------------------------------------
# Public reference data (school mottos/facts are public - no auth needed)
# ---------------------------------------------------------------------------
 
@router.get("/search")
def schools_search(q: str = Query("", max_length=200)):
    """Autocomplete for the survey school picker. School names and mottos
    are public reference data, so this needs no auth - it's a directory
    lookup, not user data."""
    return {"results": search_schools(q)}
 
 
@router.get("/lookup")
def schools_lookup(name: str = Query("", max_length=200)):
    """Resolve one school name/alias to its curated profile, or null.
    Public reference data (same rationale as /search)."""
    return {"school": lookup_school(name)}
 
 
# ---------------------------------------------------------------------------
# Per-student admissions intelligence (auth-protected to that user)
# ---------------------------------------------------------------------------
 
@router.get("/guidance/{user_id}")
def schools_guidance(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-tailored admissions guidance for a specific student -
    each target school's real profile + guidance, plus an honest note for
    any school not in the curated set."""
    return school_guidance_for_profile(_load_student_profile(user_id, db))
 
 
@router.get("/roadmap/{user_id}")
def schools_roadmap(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-aware admissions roadmap for a student - branches
    US-holistic vs UK-course-specific on their anchor school, weaves in that
    school's real values, and stays honest about data depth. Deterministic;
    no fabricated per-school tactics."""
    return generate_admissions_roadmap(_load_student_profile(user_id, db))
 
 
@router.post("/essay/{user_id}")
def schools_essay(user_id: str, payload: dict = Body(default={}), db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """A school-aware application-essay scaffold for a student. Branches the
    US personal-narrative essay vs the UK subject-focused UCAS statement (the
    two are genuinely different), weaving in the anchor school's real values.
    Honest scaffolding only - never a written-for-you essay. Body may include
    an optional 'theme' string (the story/trait the essay should show)."""
    theme = ""
    if isinstance(payload, dict):
        theme = str(payload.get("theme", ""))[:300]
    return essay_structure(_load_student_profile(user_id, db), theme)
 
 
@router.get("/deadlines/{user_id}")
def schools_deadlines(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """School-aware application-deadline reminders for the student's target
    countries (real, well-known UCAS/ED/EA dates; no fabricated per-school
    specifics)."""
    return {"deadlines": admissions_deadline_context(_load_student_profile(user_id, db))}
 
 
@router.get("/assistant-context/{user_id}")
def schools_assistant_context(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-aware system prompt for an admissions AI guide, built from
    the student's profile and target schools. Lets a server-side assistant
    give the same school-specific, honest guidance the frontend Metis does."""
    return {"system": admissions_assistant_context(_load_student_profile(user_id, db))}
 
 
 
@router.get("/readiness/{user_id}")
def schools_readiness(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """X-factor: an honest, evidence-based read of where the student stands for
    EACH target school - a readiness band (never a fake admit probability), the
    real evidence behind it, and the single highest-leverage next move per
    school. Assembles activity signals from stored data where available."""
    profile = _load_student_profile(user_id, db)
    # Best-effort activity signals from stored records; readiness degrades
    # gracefully to profile-only evidence if these tables aren't populated.
    signals = {}
    try:
        from app.models.db_models import Application
        apps = db.query(Application).filter(Application.user_id == user_id).all()
        signals["tracked_count"] = len(apps)
    except Exception:
        pass
    return admissions_readiness(profile, signals)
 
