from fastapi import APIRouter, HTTPException, Depends, Query, Header
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.auth import require_auth_for_user
from app.services.schools import (
    search_schools,
    lookup_school,
    school_guidance_for_profile,
    tailor_advice_for_opportunity,
)
 
router = APIRouter(prefix="/schools", tags=["schools"])
 
 
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
    school = lookup_school(name)
    return {"school": school}
 
 
@router.get("/guidance/{user_id}")
def schools_guidance(user_id: str, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The school-tailored admissions guidance for a specific student -
    each of their target schools' real profile + guidance, plus an honest
    note for any target schools not in the curated set. Reads the student's
    stored profile, so it's auth-protected to that user."""
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
 
    profile_dict = {
        "intended_major": profile.intended_major,
        "grade_level": profile.grade_level,
        "target_schools": profile.target_schools,
        "interests": profile.interests,
    }
    return school_guidance_for_profile(profile_dict)
 
